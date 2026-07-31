from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_user_blocked_from_reviews"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="fleet_logging_public",
            field=models.BooleanField(default=True),
        ),
    ]
