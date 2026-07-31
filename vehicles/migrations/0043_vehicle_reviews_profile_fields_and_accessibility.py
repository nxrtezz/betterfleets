from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0042_historicallivery_creator"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclefeature",
            name="category",
            field=models.CharField(
                choices=[("feature", "Feature"), ("accessibility", "Accessibility")],
                default="feature",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="rear_advert",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.CreateModel(
            name="VehicleReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating", models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
                ("message", models.TextField(max_length=2000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="vehicle_reviews", to=settings.AUTH_USER_MODEL)),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reviews", to="vehicles.vehicle")),
            ],
            options={"ordering": ("-updated_at", "-created_at")},
        ),
        migrations.AddConstraint(
            model_name="vehiclereview",
            constraint=models.UniqueConstraint(fields=("user", "vehicle"), name="unique_vehicle_review_per_user"),
        ),
    ]
