from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0025_operator_and_group_social_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="fleet_list_notes",
            field=models.TextField(
                blank=True,
                help_text=(
                    "For preserved operators, optional replacement text for the note "
                    "shown above the fleet list."
                ),
            ),
        ),
    ]