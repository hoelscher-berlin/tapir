from django.urls import path

from tapir.coop import views

app_name = "coop"
urlpatterns = [
    path(
        "share/<int:pk>/edit",
        views.ShareOwnershipUpdateView.as_view(),
        name="share_update",
    ),
    path(
        "share/<int:pk>/delete",
        views.share_ownership_delete,
        name="shareownership_delete",
    ),
    path("user/draft/", views.DraftUserListView.as_view(), name="draftuser_list"),
    path(
        "user/draft/create",
        views.DraftUserCreateView.as_view(),
        name="draftuser_create",
    ),
    path(
        "user/draft/register",
        views.DraftUserRegisterView.as_view(),
        name="draftuser_register",
    ),
    path(
        "user/draft/register/confirm",
        views.DraftUserConfirmRegistrationView.as_view(),
        name="draftuser_confirm_registration",
    ),
    path(
        "user/draft/<int:pk>/edit",
        views.DraftUserUpdateView.as_view(),
        name="draftuser_update",
    ),
    path(
        "user/draft/<int:pk>",
        views.DraftUserDetailView.as_view(),
        name="draftuser_detail",
    ),
    path(
        "user/draft/<int:pk>/delete",
        views.DraftUserDeleteView.as_view(),
        name="draftuser_delete",
    ),
    path(
        "user/draft/<int:pk>/signed_membership_agreement",
        views.mark_signed_membership_agreement,
        name="mark_draftuser_signed_membership_agreement",
    ),
    path(
        "user/draft/<int:pk>/attended_welcome_session",
        views.mark_attended_welcome_session,
        name="mark_draftuser_attended_welcome_session",
    ),
    path(
        "member/<int:pk>/attended_welcome_session",
        views.mark_shareowner_attended_welcome_session,
        name="mark_shareowner_attended_welcome_session",
    ),
    path(
        "user/draft/<int:pk>/membership_agreement",
        views.draftuser_membership_agreement,
        name="draftuser_membership_agreement",
    ),
    path(
        "membership_agreement",
        views.empty_membership_agreement,
        name="empty_membership_agreement",
    ),
    path(
        "member/<int:shareowner_pk>/create_shareownership",
        views.ShareOwnershipCreateView.as_view(),
        name="share_create",
    ),
    path(
        "member/<int:shareowner_pk>/create_user",
        views.CreateUserFromShareOwnerView.as_view(),
        name="create_user_from_shareowner",
    ),
    path(
        "user/draft/<int:pk>/draftuser_create_share_owner",
        views.create_share_owner_from_draftuser,
        name="draftuser_create_share_owner",
    ),
    path(
        "member/",
        views.ShareOwnerListView.as_view(),
        name="shareowner_list",
    ),
    path(
        "member/export/mailchimp",
        views.ShareOwnerExportMailchimpView.as_view(),
        name="shareowner_export_mailchimp",
    ),
    path(
        "member/<int:pk>/membership_confirmation",
        views.shareowner_membership_confirmation,
        name="shareowner_membership_confirmation",
    ),
    path(
        "member/<int:pk>/membership_agreement",
        views.shareowner_membership_agreement,
        name="shareowner_membership_agreement",
    ),
    path(
        "member/<int:pk>/membership_confirmation/send",
        views.send_shareowner_membership_confirmation_welcome_email,
        name="send_shareowner_membership_confirmation_welcome_email",
    ),
    path(
        "user/draft/<int:pk>/register_payment",
        views.register_draftuser_payment,
        name="register_draftuser_payment",
    ),
    path(
        "member/<int:pk>/",
        views.ShareOwnerDetailView.as_view(),
        name="shareowner_detail",
    ),
    path(
        "member/<int:pk>/edit",
        views.ShareOwnerUpdateView.as_view(),
        name="shareowner_update",
    ),
]
