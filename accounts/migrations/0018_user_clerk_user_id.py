from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0017_user_advanced_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="clerk_user_id",
            field=models.CharField(
                blank=True,
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
    ]
