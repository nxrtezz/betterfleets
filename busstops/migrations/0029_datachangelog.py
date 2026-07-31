from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("busstops", "0028_route_notice"),
    ]

    operations = [
        migrations.CreateModel(
            name="DataChangeLog",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("source", models.CharField(db_index=True, max_length=120)),
                ("target_model", models.CharField(db_index=True, max_length=100)),
                (
                    "target_pk",
                    models.CharField(blank=True, db_index=True, max_length=100),
                ),
                ("target_repr", models.CharField(blank=True, max_length=255)),
                (
                    "operation",
                    models.CharField(db_index=True, default="update", max_length=20),
                ),
                ("changes", models.JSONField(blank=True, default=dict)),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending approval"),
                            ("applied", "Applied"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_data_change_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="datachangelog",
            index=models.Index(
                fields=["status", "target_model"],
                name="busstops_da_status_8f8229_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="datachangelog",
            index=models.Index(
                fields=["source", "created_at"],
                name="busstops_da_source_3b9f8a_idx",
            ),
        ),
    ]
