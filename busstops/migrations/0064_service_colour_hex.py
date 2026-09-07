from django.db import migrations, models


def sync_colour_column(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'busstops_service'
              AND table_schema = current_schema()
              AND column_name IN ('colour', 'colour_id')
            """
        )
        columns = {row[0] for row in cursor.fetchall()}

        if "colour" not in columns:
            cursor.execute(
                "ALTER TABLE busstops_service"
                " ADD COLUMN colour varchar(7) NOT NULL DEFAULT ''"
            )
            cursor.execute(
                "ALTER TABLE busstops_service ALTER COLUMN colour DROP DEFAULT"
            )

        if "colour_id" in columns:
            cursor.execute(
                """
                UPDATE busstops_service
                SET colour = busstops_servicecolour.background
                FROM busstops_servicecolour
                WHERE busstops_servicecolour.id = busstops_service.colour_id
                  AND busstops_service.colour = ''
                  AND busstops_servicecolour.background ~ '^#[0-9A-Fa-f]{6}$'
                """
            )
            cursor.execute("ALTER TABLE busstops_service DROP COLUMN colour_id")


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0063_governmentauthority_operator_government_authority"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(sync_colour_column, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="service",
                    name="colour",
                ),
                migrations.AddField(
                    model_name="service",
                    name="colour",
                    field=models.CharField(
                        blank=True,
                        help_text="Hex colour code e.g. #0055aa",
                        max_length=7,
                    ),
                ),
            ],
        ),
    ]
