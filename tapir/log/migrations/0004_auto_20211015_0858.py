# Generated by Django 3.1.13 on 2021-10-15 06:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("log", "0003_textlogentry"),
    ]

    operations = [
        migrations.AlterField(
            model_name="logentry",
            name="created_date",
            field=models.DateTimeField(auto_now_add=True, verbose_name="Creation Date"),
        ),
    ]