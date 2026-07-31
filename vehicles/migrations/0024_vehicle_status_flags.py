from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0023_vehicle_prev_registration"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="awaiting_delivery",
            field=models.BooleanField(
                default=False,
                help_text="Use for vehicles that are still awaiting delivery or entry into service.",
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="fleet_support_vehicle",
            field=models.BooleanField(
                default=False,
                help_text="Use for fleet support vehicles. This stays in sync with feature 8.",
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="trainer_vehicle",
            field=models.BooleanField(
                default=False,
                help_text="Use for vehicles primarily assigned to training duties.",
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="vor",
            field=models.BooleanField(
                default=False,
                help_text="Vehicle off road.",
                verbose_name="VOR",
            ),
        ),
    ]
