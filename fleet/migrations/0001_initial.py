from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FleetPDFUpload",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="fleet-pdfs/")),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
            ],
            options={"ordering": ("-uploaded_at",)},
        ),
        migrations.CreateModel(
            name="FleetVehicle",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operator_code", models.CharField(db_index=True, default="EXLS", max_length=32)),
                ("external_id", models.CharField(blank=True, max_length=100)),
                ("code", models.CharField(blank=True, max_length=64)),
                ("fleet_number", models.CharField(blank=True, db_index=True, max_length=32)),
                ("fleet_code", models.CharField(blank=True, db_index=True, max_length=32)),
                ("registration", models.CharField(blank=True, db_index=True, max_length=24)),
                ("prev_registration", models.CharField(blank=True, max_length=255)),
                ("vehicle_type", models.CharField(blank=True, db_index=True, max_length=255)),
                ("livery", models.CharField(blank=True, db_index=True, max_length=255)),
                ("colours", models.CharField(blank=True, max_length=255)),
                ("garage", models.CharField(blank=True, db_index=True, max_length=255)),
                ("name", models.CharField(blank=True, max_length=255)),
                ("branding", models.CharField(blank=True, max_length=255)),
                ("notes", models.TextField(blank=True)),
                ("withdrawn", models.BooleanField(default=False)),
                ("preserved", models.BooleanField(default=False)),
                ("fleet_support_vehicle", models.BooleanField(default=False)),
                ("vor", models.BooleanField(default=False)),
                ("awaiting_delivery", models.BooleanField(default=False)),
                ("trainer_vehicle", models.BooleanField(default=False)),
                ("demonstrator", models.BooleanField(default=False)),
                ("source_page", models.PositiveIntegerField(default=1)),
                ("raw_text", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source_pdf",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vehicles",
                        to="fleet.fleetpdfupload",
                    ),
                ),
            ],
            options={
                "ordering": ("source_pdf", "source_page", "fleet_number", "fleet_code", "code")
            },
        ),
    ]
