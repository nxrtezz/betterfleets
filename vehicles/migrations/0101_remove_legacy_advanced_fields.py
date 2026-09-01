import json

from django.db import migrations


LEGACY_ADVANCED_FIELD_NAMES = {
    "engine": "engine",
    "gearbox": "gearbox",
    "length": "length",
    "capacity": "capacity",
    "seating-capacity": "capacity",
    "seating_capacity": "capacity",
    "emissions_rating": "emissions_rating",
    "emissions-rating": "emissions_rating",
    "emissions": "emissions_rating",
    "chassis": "chassis",
}


def text_value(value):
    return "" if value is None else str(value)


def migrate_legacy_revision_changes(apps, schema_editor):
    VehicleRevision = apps.get_model("vehicles", "VehicleRevision")
    for revision in VehicleRevision.objects.exclude(changes__isnull=True).iterator():
        changes = dict(revision.changes)
        updated = False
        for key in tuple(changes):
            if not key.startswith("advanced:"):
                continue
            field_name = LEGACY_ADVANCED_FIELD_NAMES.get(key.split(":", 1)[1])
            value = changes.pop(key)
            updated = True
            if not field_name:
                continue
            before, after = value.split("\n+", 1)
            changes[field_name] = (
                f"-{text_value(json.loads(before[1:]))}\n+"
                f"{text_value(json.loads(after))}"
            )
        if updated:
            revision.changes = changes
            revision.save(update_fields=["changes"])


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0100_vehicle_technical_specifications"),
    ]

    operations = [
        migrations.RunPython(
            migrate_legacy_revision_changes,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="vehicle",
            name="advanced",
        ),
        migrations.DeleteModel(
            name="AdvancedField",
        ),
    ]
