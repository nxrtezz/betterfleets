from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_user_discord_widget_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="blocked_from_reviews",
            field=models.BooleanField(default=False),
        ),
    ]
