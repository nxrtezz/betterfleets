from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0041_livery_creator"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicallivery",
            name="creator",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
