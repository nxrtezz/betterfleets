from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0023_service_garage"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="special_service",
            field=models.BooleanField(null=True),
        ),
    ]
