from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0014_operator_fleet_metadata"),
    ]

    operations = [
        migrations.CreateModel(
            name="HomepageNotice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, max_length=120)),
                ("message", models.TextField()),
                ("from_date", models.DateField(blank=True, null=True)),
                ("to_date", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-from_date", "-modified_at", "-id")},
        ),
    ]
