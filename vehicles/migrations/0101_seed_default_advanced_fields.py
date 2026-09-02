# Seeds the standard set of AdvancedField definitions (Chassis, Gearbox,
# Engine, Seating capacity) that were previously only present as data in
# the admin-managed vehicles_advancedfield table. That table was missing
# entirely on some databases (see 0100_fix_missing_advancedfield_table),
# so any rows that existed there were lost.
#
# The slugs here ("engine", "seating-capacity", "gearbox") match what
# busstops/fleet_imports.py and fleet/exporters/xlsx.py already expect in
# Vehicle.advanced. "chassis" is included as a plain text field for parity
# since it's part of the same standard set.

from django.db import migrations

DEFAULT_ADVANCED_FIELDS = [
    {"name": "Chassis", "slug": "chassis", "field_type": "text", "display_order": 0},
    {"name": "Gearbox", "slug": "gearbox", "field_type": "text", "display_order": 1},
    {"name": "Engine", "slug": "engine", "field_type": "text", "display_order": 2},
    {
        "name": "Seating capacity",
        "slug": "seating-capacity",
        "field_type": "number",
        "display_order": 3,
    },
]


def seed_default_advanced_fields(apps, schema_editor):
    AdvancedField = apps.get_model("vehicles", "AdvancedField")
    for defaults in DEFAULT_ADVANCED_FIELDS:
        slug = defaults["slug"]
        if not AdvancedField.objects.filter(slug=slug).exists():
            AdvancedField.objects.create(**defaults)


def remove_default_advanced_fields(apps, schema_editor):
    AdvancedField = apps.get_model("vehicles", "AdvancedField")
    AdvancedField.objects.filter(
        slug__in=[f["slug"] for f in DEFAULT_ADVANCED_FIELDS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0100_fix_missing_advancedfield_table"),
    ]

    operations = [
        migrations.RunPython(
            seed_default_advanced_fields, remove_default_advanced_fields
        ),
    ]
