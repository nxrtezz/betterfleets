from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0034_vehicletype_manufacturer"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicletype",
            name="active_production",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="vehicletype",
            name="primary_type",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"primary_type__isnull": True},
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="variants",
                to="vehicles.vehicletype",
            ),
        ),
    ]
