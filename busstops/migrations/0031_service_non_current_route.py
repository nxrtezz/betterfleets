from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0030_manufacturer_and_sites"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="non_current_route",
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
