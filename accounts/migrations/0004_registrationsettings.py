from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_invitation"),
    ]

    operations = [
        migrations.CreateModel(
            name="RegistrationSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("require_invite_codes", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name_plural": "registration settings",
            },
        ),
    ]
