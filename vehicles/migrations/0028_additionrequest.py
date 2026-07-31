from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("vehicles", "0027_historical_snapshot_vehicles"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdditionRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_type", models.CharField(choices=[("livery", "Liveries"), ("vehicle_type", "Vehicles"), ("operator", "Operators"), ("garage", "Garage")], max_length=20)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("created_object_id", models.CharField(blank=True, max_length=64)),
                ("created_object_repr", models.CharField(blank=True, max_length=255)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="addition_requests", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_addition_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("status", "-created_at"),
            },
        ),
    ]
