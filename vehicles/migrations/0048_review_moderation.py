from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


BLOCKED_PHRASES = [
    ("nigger", "racial slur"),
    ("nigga", "racial slur"),
    ("paki", "racial slur"),
    ("kike", "racial slur"),
    ("coon", "racial slur"),
    ("spic", "racial slur"),
    ("gook", "racial slur"),
    ("wetback", "racial slur"),
    ("chink", "racial slur"),
    ("raghead", "racial slur"),
    ("sandnigger", "racial slur"),
    ("tranny", "anti-trans slur"),
    ("faggot", "anti-gay slur"),
    ("retard", "ableist slur"),
    ("kill yourself", "self-harm encouragement"),
]


def seed_blocked_phrases(apps, schema_editor):
    ReviewBlockedPhrase = apps.get_model("vehicles", "ReviewBlockedPhrase")
    for phrase, notes in BLOCKED_PHRASES:
        ReviewBlockedPhrase.objects.get_or_create(
            phrase=phrase,
            defaults={
                "normalized_phrase": "".join(
                    ch for ch in phrase.casefold() if ch.isalnum()
                ),
                "notes": notes,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0047_vehicle_dvla_euro_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclereview",
            name="flagged_terms",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="vehiclereview",
            name="moderation_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="vehiclereview",
            name="status",
            field=models.CharField(
                choices=[
                    ("published", "Published"),
                    ("pending", "Pending moderation"),
                    ("hidden", "Hidden"),
                ],
                db_index=True,
                default="published",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="ReviewBlockedPhrase",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phrase", models.CharField(max_length=255, unique=True)),
                ("normalized_phrase", models.CharField(db_index=True, editable=False, max_length=255)),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "review blocked phrase",
                "verbose_name_plural": "review blocked phrases",
                "ordering": ("phrase",),
            },
        ),
        migrations.CreateModel(
            name="VehicleReviewReport",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField(blank=True, max_length=1000)),
                ("status", models.CharField(choices=[("open", "Open"), ("resolved", "Resolved"), ("dismissed", "Dismissed")], db_index=True, default="open", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reporter", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="vehicle_review_reports", to=settings.AUTH_USER_MODEL)),
                ("review", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reports", to="vehicles.vehiclereview")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.RunPython(seed_blocked_phrases, migrations.RunPython.noop),
    ]
