from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0036_vehicletypegroup_and_vehicle_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="demonstrator",
            field=models.BooleanField(
                default=False,
                help_text="Use for demonstrators so they appear in manufacturer demonstrator fleets.",
            ),
        ),
    ]
