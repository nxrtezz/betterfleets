# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0055_rename_busstops_bu_object__7259f3_idx_busstops_bu_object__fff346_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="check_dvla",
            field=models.BooleanField(
                default=False,
                help_text="If enabled, DVLA data will be checked every 72 hours for this operator's vehicles.",
            ),
        ),
        migrations.AddField(
            model_name="operator",
            name="dvla_last_checked_at",
            field=models.DateTimeField(
                null=True,
                blank=True,
                help_text="Last time DVLA data was checked for this operator's vehicles.",
            ),
        ),
    ]
