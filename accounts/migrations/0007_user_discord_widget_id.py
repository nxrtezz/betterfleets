from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_profile_fields_and_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="discord_user_id",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
