from django.db import migrations


def drop_orphan_not_null(apps, schema_editor):
    """Make columns Django doesn't know about nullable.

    Deployed databases predate some model changes and still have columns
    (`capacity`, `engine`, `gearbox` and friends) that no model field maps to.
    Django never supplies a value for them, so a NOT NULL one without a default
    makes every INSERT fail.
    """

    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    with connection.cursor() as cursor:
        for model in apps.get_app_config("vehicles").get_models():
            table = model._meta.db_table
            known_columns = [
                field.column for field in model._meta.concrete_fields if field.column
            ]
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                  AND table_schema = current_schema()
                  AND is_nullable = 'NO'
                  AND column_default IS NULL
                  AND is_identity = 'NO'
                  AND is_generated = 'NEVER'
                  AND NOT (column_name = ANY(%s))
                """,
                [table, known_columns],
            )
            for (column,) in cursor.fetchall():
                cursor.execute(
                    f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL'
                )


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0102_fix_orphan_technical_columns"),
    ]

    operations = [
        migrations.RunPython(drop_orphan_not_null, migrations.RunPython.noop),
    ]
