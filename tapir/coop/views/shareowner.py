import csv
import datetime

import django_filters
import django_tables2
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django.views import generic
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_GET
from django.views.generic import UpdateView, FormView
from django_filters import CharFilter, ChoiceFilter, BooleanFilter
from django_filters.views import FilterView
from django_tables2 import SingleTableView
from django_tables2.export import ExportMixin

from tapir import settings
from tapir.accounts.models import TapirUser
from tapir.coop import pdfs
from tapir.coop.config import COOP_SHARE_PRICE
from tapir.coop.emails.extra_shares_confirmation_email import (
    ExtraSharesConfirmationEmail,
)
from tapir.coop.emails.membership_confirmation_email_for_active_member import (
    MembershipConfirmationForActiveMemberEmail,
)
from tapir.coop.emails.membership_confirmation_email_for_investing_member import (
    MembershipConfirmationForInvestingMemberEmail,
)
from tapir.coop.emails.tapir_account_created_email import TapirAccountCreatedEmail
from tapir.coop.forms import (
    ShareOwnershipForm,
    ShareOwnerForm,
    ShareOwnershipCreateMultipleForm,
)
from tapir.coop.models import (
    ShareOwnership,
    ShareOwner,
    UpdateShareOwnerLogEntry,
    DeleteShareOwnershipLogEntry,
    MEMBER_STATUS_CHOICES,
    MemberStatus,
    get_member_status_translation,
    CreateShareOwnershipsLogEntry,
    UpdateShareOwnershipLogEntry,
    ExtraSharesForAccountingRecap,
)
from tapir.log.models import LogEntry
from tapir.log.util import freeze_for_log
from tapir.log.views import UpdateViewLogMixin
from tapir.shifts.models import (
    ShiftUserData,
    SHIFT_USER_CAPABILITY_CHOICES,
    ShiftAttendanceTemplate,
    ShiftAttendanceMode,
)
from tapir.utils.models import copy_user_info


class ShareOwnershipViewMixin:
    model = ShareOwnership
    form_class = ShareOwnershipForm

    def get_success_url(self):
        # After successful creation or update of a ShareOwnership, return to the user overview page.
        return self.object.owner.get_absolute_url()


class ShareOwnershipUpdateView(
    PermissionRequiredMixin, UpdateViewLogMixin, ShareOwnershipViewMixin, UpdateView
):
    permission_required = "coop.manage"

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)

            new_frozen = freeze_for_log(form.instance)
            if self.old_object_frozen != new_frozen:
                log_entry = UpdateShareOwnershipLogEntry().populate(
                    share_ownership=form.instance,
                    old_frozen=self.old_object_frozen,
                    new_frozen=new_frozen,
                    share_owner=form.instance.owner,
                    actor=self.request.user,
                )
                log_entry.save()

            return response


class ShareOwnershipCreateMultipleView(PermissionRequiredMixin, FormView):
    form_class = ShareOwnershipCreateMultipleForm
    permission_required = "coop.manage"
    template_name = "core/generic_form.html"

    def get_share_owner(self) -> ShareOwner:
        return get_object_or_404(ShareOwner, pk=self.kwargs["shareowner_pk"])

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data["card_title"] = _(f"Add shares to %(name)s") % {
            "name": self.get_share_owner().get_info().get_display_name()
        }
        return context_data

    def form_valid(self, form):
        share_owner = self.get_share_owner()
        num_shares = form.cleaned_data["num_shares"]

        with transaction.atomic():
            CreateShareOwnershipsLogEntry().populate(
                num_shares=num_shares,
                start_date=form.cleaned_data["start_date"],
                end_date=form.cleaned_data["end_date"],
                actor=self.request.user,
                user=share_owner.user,
                share_owner=share_owner,
            ).save()

            for _ in range(form.cleaned_data["num_shares"]):
                ShareOwnership.objects.create(
                    owner=share_owner,
                    amount_paid=0,
                    start_date=form.cleaned_data["start_date"],
                    end_date=form.cleaned_data["end_date"],
                )

            ExtraSharesForAccountingRecap.objects.create(
                member=share_owner,
                number_of_shares=num_shares,
                date=timezone.now().date(),
            )

        email = ExtraSharesConfirmationEmail(
            num_shares=form.cleaned_data["num_shares"], share_owner=share_owner
        )
        email.send_to_share_owner(actor=self.request.user, recipient=share_owner)

        return super().form_valid(form)

    def get_success_url(self):
        return self.get_share_owner().get_info().get_absolute_url()


@require_POST
@csrf_protect
# Higher permission requirement since this is a destructive operation only to correct mistakes
@permission_required("coop.admin")
def share_ownership_delete(request, pk):
    share_ownership = get_object_or_404(ShareOwnership, pk=pk)
    owner = share_ownership.owner

    with transaction.atomic():
        DeleteShareOwnershipLogEntry().populate(
            share_owner=share_ownership.owner, actor=request.user, model=share_ownership
        ).save()
        share_ownership.delete()

    return redirect(owner)


class ShareOwnerDetailView(PermissionRequiredMixin, generic.DetailView):
    model = ShareOwner
    permission_required = "coop.manage"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.user:
            return redirect(self.object.user)
        return super().get(request, *args, **kwargs)


class ShareOwnerUpdateView(
    PermissionRequiredMixin, UpdateViewLogMixin, generic.UpdateView
):
    permission_required = "accounts.manage"
    model = ShareOwner
    form_class = ShareOwnerForm

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)

            new_frozen = freeze_for_log(form.instance)
            if self.old_object_frozen != new_frozen:
                log_entry = UpdateShareOwnerLogEntry().populate(
                    old_frozen=self.old_object_frozen,
                    new_frozen=new_frozen,
                    share_owner=form.instance,
                    actor=self.request.user,
                )
                log_entry.save()

            return response


@require_GET
@permission_required("coop.manage")
def empty_membership_agreement(request):
    filename = "Beteiligungserklärung " + settings.COOP_NAME + ".pdf"
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="{}"'.format(filename)
    response.write(pdfs.get_membership_agreement_pdf().write_pdf())
    return response


@require_POST
@csrf_protect
@permission_required("coop.manage")
def mark_shareowner_attended_welcome_session(request, pk):
    share_owner = get_object_or_404(ShareOwner, pk=pk)
    old_share_owner_dict = freeze_for_log(share_owner)

    with transaction.atomic():
        share_owner.attended_welcome_session = True
        share_owner.save()

        log_entry = UpdateShareOwnerLogEntry().populate(
            old_frozen=old_share_owner_dict,
            new_model=share_owner,
            share_owner=share_owner,
            actor=request.user,
        )
        log_entry.save()

    return redirect(share_owner.get_absolute_url())


class CreateUserFromShareOwnerView(PermissionRequiredMixin, generic.CreateView):
    model = TapirUser
    template_name = "coop/create_user_from_shareowner_form.html"
    permission_required = "coop.manage"
    fields = ["first_name", "last_name", "username"]

    def get_shareowner(self):
        return get_object_or_404(ShareOwner, pk=self.kwargs["shareowner_pk"])

    def dispatch(self, request, *args, **kwargs):
        owner = self.get_shareowner()
        # Not sure if 403 is the right error code here...
        if owner.user is not None:
            return HttpResponseForbidden("This ShareOwner already has a User")
        if owner.is_company:
            return HttpResponseForbidden("This ShareOwner is a company")

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        owner = self.get_shareowner()
        user = TapirUser()
        copy_user_info(owner, user)
        kwargs.update({"instance": user})
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            owner = self.get_shareowner()
            owner.user = form.instance
            owner.blank_info_fields()
            owner.save()

            LogEntry.objects.filter(share_owner=owner).update(
                user=form.instance, share_owner=None
            )
            email = TapirAccountCreatedEmail(tapir_user=owner.user)
            email.send_to_tapir_user(actor=self.request.user, recipient=owner.user)
            return response


@require_POST
@csrf_protect
@permission_required("coop.manage")
def send_shareowner_membership_confirmation_welcome_email(request, pk):
    share_owner = get_object_or_404(ShareOwner, pk=pk)

    email = (
        MembershipConfirmationForInvestingMemberEmail
        if share_owner.is_investing
        else MembershipConfirmationForActiveMemberEmail
    )(share_owner=share_owner)
    email.send_to_share_owner(actor=request.user, recipient=share_owner)

    messages.info(request, _("Membership confirmation email sent."))

    return redirect(share_owner.get_absolute_url())


@require_GET
@permission_required("coop.manage")
def shareowner_membership_confirmation(request, pk):
    owner = get_object_or_404(ShareOwner, pk=pk)
    filename = "Mitgliedschaftsbestätigung %s.pdf" % owner.get_info().get_display_name()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'filename="{}"'.format(filename)

    num_shares = (
        request.GET["num_shares"]
        if "num_shares" in request.GET.keys()
        else owner.get_active_share_ownerships().count()
    )
    date = (
        datetime.datetime.strptime(request.GET["date"], "%d.%m.%Y").date()
        if "date" in request.GET.keys()
        else timezone.now().date()
    )

    pdf = pdfs.get_shareowner_membership_confirmation_pdf(
        owner,
        num_shares=num_shares,
        date=date,
    )
    response.write(pdf.write_pdf())
    return response


@require_GET
@permission_required("coop.manage")
def shareowner_extra_shares_confirmation(request, pk):
    share_owner = get_object_or_404(ShareOwner, pk=pk)
    filename = (
        "Bestätigung Erwerb Anteile %s.pdf" % share_owner.get_info().get_display_name()
    )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'filename="{}"'.format(filename)

    if "num_shares" not in request.GET.keys():
        raise ValidationError("Missing parameter : num_shares")
    num_shares = request.GET["num_shares"]

    if "date" not in request.GET.keys():
        raise ValidationError("Missing parameter : date")
    date = datetime.datetime.strptime(request.GET["date"], "%d.%m.%Y").date()

    pdf = pdfs.get_confirmation_extra_shares_pdf(
        share_owner,
        num_shares=num_shares,
        date=date,
    )
    response.write(pdf.write_pdf())
    return response


@require_GET
@permission_required("coop.manage")
def shareowner_membership_agreement(request, pk):
    owner = get_object_or_404(ShareOwner, pk=pk)
    filename = "Beteiligungserklärung %s.pdf" % owner.get_display_name()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'filename="{}"'.format(filename)
    response.write(pdfs.get_membership_agreement_pdf(owner).write_pdf())
    return response


class CurrentShareOwnerMixin:
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(share_ownerships__in=ShareOwnership.objects.active_temporal())
            .distinct()
        )


class ShareOwnerTable(django_tables2.Table):
    class Meta:
        model = ShareOwner
        template_name = "django_tables2/bootstrap4.html"
        fields = [
            "id",
            "attended_welcome_session",
            "ratenzahlung",
            "is_company",
        ]
        sequence = (
            "id",
            "display_name",
            "first_name",
            "last_name",
            "street",
            "postcode",
            "city",
            "country",
            "status",
            "attended_welcome_session",
            "ratenzahlung",
            "is_company",
        )
        order_by = "id"

    display_name = django_tables2.Column(
        empty_values=(), verbose_name="Name", orderable=False, exclude_from_export=True
    )
    first_name = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    last_name = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    street = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    postcode = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    city = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    country = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    status = django_tables2.Column(empty_values=(), orderable=False)
    email = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    phone_number = django_tables2.Column(
        empty_values=(), orderable=False, visible=False
    )
    company_name = django_tables2.Column(
        empty_values=(), orderable=False, visible=False
    )
    preferred_language = django_tables2.Column(
        empty_values=(), orderable=False, visible=False
    )
    num_shares = django_tables2.Column(empty_values=(), orderable=False, visible=False)
    join_date = django_tables2.Column(empty_values=(), orderable=False, visible=False)

    @staticmethod
    def render_display_name(value, record: ShareOwner):
        return format_html(
            "<a href={}>{}</a>",
            record.get_absolute_url(),
            record.get_info().get_display_name(),
        )

    @staticmethod
    def value_display_name(value, record: ShareOwner):
        return record.get_info().get_display_name()

    @staticmethod
    def value_first_name(value, record: ShareOwner):
        return record.get_info().first_name

    @staticmethod
    def value_last_name(value, record: ShareOwner):
        return record.get_info().last_name

    @staticmethod
    def value_postcode(value, record: ShareOwner):
        return record.get_info().postcode

    @staticmethod
    def render_postcode(value, record: ShareOwner):
        return record.get_info().postcode

    @staticmethod
    def value_street(value, record: ShareOwner):
        return record.get_info().street

    @staticmethod
    def render_street(value, record: ShareOwner):
        return record.get_info().street

    @staticmethod
    def value_city(value, record: ShareOwner):
        return record.get_info().city

    @staticmethod
    def render_city(value, record: ShareOwner):
        return record.get_info().city

    @staticmethod
    def value_country(value, record: ShareOwner):
        return record.get_info().country

    @staticmethod
    def render_country(value, record: ShareOwner):
        return record.get_info().country

    @staticmethod
    def render_status(value, record: ShareOwner):
        status = record.get_member_status()
        if status == MemberStatus.SOLD:
            color = "orange"
        elif status == MemberStatus.ACTIVE:
            color = "green"
        else:
            color = "blue"

        return format_html(
            '<span style="color: {1};">{0}</span>',
            get_member_status_translation(status),
            color,
        )

    @staticmethod
    def value_status(value, record: ShareOwner):
        return record.get_member_status()

    @staticmethod
    def value_email(value, record: ShareOwner):
        return record.get_info().email

    @staticmethod
    def value_phone_number(value, record: ShareOwner):
        return record.get_info().phone_number

    @staticmethod
    def value_preferred_language(value, record: ShareOwner):
        return record.get_info().preferred_language

    @staticmethod
    def value_num_shares(value, record: ShareOwner):
        return record.num_shares()

    @staticmethod
    def value_join_date(value, record: ShareOwner):
        ownership = record.get_oldest_active_share_ownership()
        return ownership.start_date if ownership is not None else ""


class ShareOwnerFilter(django_filters.FilterSet):
    class Meta:
        model = ShareOwner
        fields = [
            "attended_welcome_session",
            "ratenzahlung",
            "is_company",
            "paid_membership_fee",
        ]

    status = ChoiceFilter(
        choices=MEMBER_STATUS_CHOICES,
        method="status_filter",
        label=_("Status"),
        empty_label=_("Any"),
    )
    shift_attendance_mode = ChoiceFilter(
        choices=ShiftUserData.SHIFT_ATTENDANCE_MODE_CHOICES,
        method="shift_attendance_mode_filter",
        label=_("Shift Status"),
    )
    registered_to_slot_with_capability = ChoiceFilter(
        choices=[
            (capability, capability_name)
            for capability, capability_name in SHIFT_USER_CAPABILITY_CHOICES.items()
        ],
        method="registered_to_slot_with_capability_filter",
        label=_("Is registered to a slot that requires a qualification"),
    )
    has_capability = ChoiceFilter(
        choices=[
            (capability, capability_name)
            for capability, capability_name in SHIFT_USER_CAPABILITY_CHOICES.items()
        ],
        method="has_capability_filter",
        label=_("Has qualification"),
    )
    not_has_capability = ChoiceFilter(
        choices=[
            (capability, capability_name)
            for capability, capability_name in SHIFT_USER_CAPABILITY_CHOICES.items()
        ],
        method="not_has_capability_filter",
        label=_("Does not have qualification"),
    )
    has_tapir_account = BooleanFilter(
        method="has_tapir_account_filter", label="Has a Tapir account"
    )
    # Théo 17.09.21 : It would be nicer to get the values from the DB, but that raises exceptions
    # when creating a brand new docker instance, because the corresponding table doesn't exist yet.
    abcd_week = ChoiceFilter(
        choices=[("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")],
        method="abcd_week_filter",
        label=_("ABCD Week"),
    )
    has_unpaid_shares = BooleanFilter(
        method="has_unpaid_shares_filter", label=_("Has unpaid shares")
    )
    is_fully_paid = BooleanFilter(
        method="is_fully_paid_filter", label=_("Is fully paid")
    )
    display_name = CharFilter(
        method="display_name_filter", label=_("Name or member ID")
    )

    @staticmethod
    def display_name_filter(queryset: ShareOwner.ShareOwnerQuerySet, name, value: str):
        # This is an ugly hack to enable searching by Mitgliedsnummer from the
        # one-stop search box in the top right
        if value.isdigit():
            return queryset.filter(id=int(value))

        return queryset.with_name(value).distinct()

    @staticmethod
    def status_filter(queryset: ShareOwner.ShareOwnerQuerySet, name, value: str):
        return queryset.with_status(value).distinct()

    @staticmethod
    def shift_attendance_mode_filter(
        queryset: ShareOwner.ShareOwnerQuerySet, name, value: str
    ):
        return queryset.filter(
            user__in=TapirUser.objects.with_shift_attendance_mode(value)
        ).distinct()

    @staticmethod
    def registered_to_slot_with_capability_filter(
        queryset: ShareOwner.ShareOwnerQuerySet, name, value: str
    ):
        return queryset.filter(
            user__in=TapirUser.objects.registered_to_shift_slot_with_capability(value)
        ).distinct()

    @staticmethod
    def has_capability_filter(
        queryset: ShareOwner.ShareOwnerQuerySet, name, value: str
    ):
        return queryset.filter(
            user__in=TapirUser.objects.has_capability(value)
        ).distinct()

    @staticmethod
    def not_has_capability_filter(
        queryset: ShareOwner.ShareOwnerQuerySet, name, value: str
    ):
        return queryset.exclude(
            user__in=TapirUser.objects.has_capability(value)
        ).distinct()

    @staticmethod
    def has_tapir_account_filter(
        queryset: ShareOwner.ShareOwnerQuerySet, name, value: bool
    ):
        return queryset.exclude(user__isnull=value).distinct()

    @staticmethod
    def abcd_week_filter(queryset: ShareOwner.ShareOwnerQuerySet, name, value: str):
        return queryset.filter(
            user__shift_attendance_templates__slot_template__shift_template__group__name=value
        ).distinct()

    @staticmethod
    def has_unpaid_shares_filter(
        queryset: ShareOwner.ShareOwnerQuerySet, name, value: bool
    ):
        unpaid_shares = ShareOwnership.objects.filter(
            amount_paid__lt=COOP_SHARE_PRICE, owner__in=queryset
        )

        if value:
            return queryset.filter(share_ownerships__in=unpaid_shares).distinct()
        else:
            return queryset.exclude(share_ownerships__in=unpaid_shares).distinct()

    def is_fully_paid_filter(
        self, queryset: ShareOwner.ShareOwnerQuerySet, name, value: bool
    ):
        return queryset.with_fully_paid(value)


class ShareOwnerListView(
    PermissionRequiredMixin, FilterView, ExportMixin, SingleTableView
):
    table_class = ShareOwnerTable
    model = ShareOwner
    template_name = "coop/shareowner_list.html"
    permission_required = "coop.manage"

    filterset_class = ShareOwnerFilter

    export_formats = ["csv", "json"]

    def get(self, request, *args, **kwargs):
        # TODO(Leon Handreke): Make FilterView properly subclasseable
        response = super().get(request, *args, **kwargs)
        if self.object_list.count() == 1:
            return HttpResponseRedirect(
                self.get_table_data().first().get_absolute_url()
            )
        return response

    def get_queryset(self):
        queryset = ShareOwner.objects.prefetch_related(
            "share_ownerships"
        ).prefetch_related("user")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filtered_member_count"] = self.object_list.count()
        context["total_member_count"] = ShareOwner.objects.count()
        return context


class ShareOwnerExportMailchimpView(
    PermissionRequiredMixin, CurrentShareOwnerMixin, generic.list.BaseListView
):
    permission_required = "coop.manage"
    model = ShareOwner

    def get_queryset(self):
        # Only active members should be on our mailing lists
        return super().get_queryset().filter(is_investing=False)

    @staticmethod
    def render_to_response(context, **response_kwargs):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="members_mailchimp.csv"'
        writer = csv.writer(response)

        writer.writerow(
            [
                "Email Address",
                "First Name",
                "Last Name",
                "Address",
                "Tags",
            ]
        )
        for owner in context["object_list"]:
            if not owner.get_info().email:
                continue

            # For some weird reason the tags are in quotes
            lang_tag = ""
            if owner.get_info().preferred_language == "de":
                lang_tag = '"Deutsch"'
            if owner.get_info().preferred_language == "en":
                lang_tag = '"English"'
            writer.writerow(
                [
                    owner.get_info().email,
                    owner.get_info().first_name,
                    owner.get_info().last_name,
                    owner.get_info().street,
                    lang_tag,
                ]
            )

        return response


class MatchingProgramTable(django_tables2.Table):
    class Meta:
        model = ShareOwner
        template_name = "django_tables2/bootstrap4.html"
        fields = [
            "willing_to_gift_a_share",
        ]
        sequence = (
            "display_name",
            "willing_to_gift_a_share",
        )
        order_by = "id"

    display_name = django_tables2.Column(
        empty_values=(), verbose_name="Name", orderable=False
    )

    @staticmethod
    def render_display_name(value, record: ShareOwner):
        return format_html(
            "<a href={}>{}</a>",
            record.get_absolute_url(),
            record.get_info().get_display_name(),
        )

    @staticmethod
    def render_willing_to_gift_a_share(value, record: ShareOwner):
        if record.willing_to_gift_a_share is None:
            return pgettext_lazy(
                context="Willing to give a share",
                message="No",
            )
        return record.willing_to_gift_a_share.strftime("%d.%m.%Y")


class MatchingProgramListView(PermissionRequiredMixin, SingleTableView):
    permission_required = "coop.manage"
    model = ShareOwner
    template_name = "coop/matching_program.html"
    table_class = MatchingProgramTable

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .exclude(willing_to_gift_a_share=None)
            .order_by("willing_to_gift_a_share")
            .prefetch_related("user")
        )


class ShareOwnerTableWelcomeDesk(django_tables2.Table):
    class Meta:
        model = ShareOwner
        template_name = "django_tables2/bootstrap4.html"
        fields = [
            "id",
        ]
        sequence = (
            "id",
            "display_name",
        )
        order_by = "id"

    display_name = django_tables2.Column(
        empty_values=(), verbose_name="Name", orderable=False
    )

    @staticmethod
    def render_display_name(value, record: ShareOwner):
        return format_html(
            "<a href={}>{}</a>",
            reverse("coop:welcome_desk_share_owner", args=[record.pk]),
            record.get_info().get_display_name(),
        )


class ShareOwnerFilterWelcomeDesk(django_filters.FilterSet):
    display_name = CharFilter(
        method="display_name_filter", label=_("Name or member ID")
    )

    @staticmethod
    def display_name_filter(queryset: ShareOwner.ShareOwnerQuerySet, name, value: str):
        if not value:
            return queryset.none()

        if value.isdigit():
            return queryset.filter(id=int(value))

        return queryset.with_name(value)


class WelcomeDeskSearchView(PermissionRequiredMixin, FilterView, SingleTableView):
    permission_required = "welcomedesk.view"
    template_name = "coop/welcome_desk_search.html"
    table_class = ShareOwnerTableWelcomeDesk
    model = ShareOwner
    filterset_class = ShareOwnerFilterWelcomeDesk

    def get_queryset(self):
        return super().get_queryset().prefetch_related("user")


class WelcomeDeskShareOwnerView(PermissionRequiredMixin, generic.DetailView):
    model = ShareOwner
    template_name = "coop/welcome_desk_share_owner.html"
    permission_required = "welcomedesk.view"
    context_object_name = "share_owner"

    def get_context_data(self, *args, **kwargs):
        context_data = super().get_context_data(*args, **kwargs)
        share_owner: ShareOwner = context_data["share_owner"]

        context_data["can_shop"] = share_owner.can_shop()

        context_data["missing_account"] = share_owner.user is None
        if context_data["missing_account"]:
            return context_data

        context_data[
            "shift_balance_not_ok"
        ] = not share_owner.user.shift_user_data.is_balance_ok()

        context_data["must_register_to_a_shift"] = (
            share_owner.user.shift_user_data.attendance_mode
            == ShiftAttendanceMode.REGULAR
            and not ShiftAttendanceTemplate.objects.filter(
                user=share_owner.user
            ).exists()
            and not share_owner.user.shift_user_data.is_currently_exempted_from_shifts()
        )

        return context_data
