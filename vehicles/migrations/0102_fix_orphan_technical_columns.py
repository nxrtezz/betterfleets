from django.db import migrations


LEGACY_TECHNICAL_COLUMNS = (
    "capacity",
    "chassis",
    "emissions_rating",
    "engine",
    "gearbox",
    "length",
)

TABLES = ("vehicles_vehicle", "vehicles_historicalvehicle")


def drop_not_null(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                  AND table_schema = current_schema()
                  AND is_nullable = 'NO'
                  AND column_default IS NULL
                  AND column_name = ANY(%s)
                """,
                [table, list(LEGACY_TECHNICAL_COLUMNS)],
            )
            for (column,) in cursor.fetchall():
                cursor.execute(
                    f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL'
                )


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0101_add_emissions_advanced_field"),
    ]

    operations = [
        migrations.RunPython(drop_not_null, migrations.RunPython.noop),
    ]
