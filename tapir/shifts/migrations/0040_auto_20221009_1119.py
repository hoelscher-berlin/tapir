# Generated by Django 3.2.15 on 2022-10-09 09:19

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("shifts", "0039_updateexemptionlogentry"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="shiftslot",
            name="optional",
        ),
        migrations.RemoveField(
            model_name="shiftslottemplate",
            name="optional",
        ),
    ]