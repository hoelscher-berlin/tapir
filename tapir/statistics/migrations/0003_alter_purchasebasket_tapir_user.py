# Generated by Django 3.2.21 on 2023-10-20 16:24

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("statistics", "0002_alter_purchasebasket_tapir_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchasebasket",
            name="tapir_user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]