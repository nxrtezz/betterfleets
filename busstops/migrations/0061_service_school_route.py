from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0060_remove_event_event_requires_operator_or_preservation_group_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="school_route",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
