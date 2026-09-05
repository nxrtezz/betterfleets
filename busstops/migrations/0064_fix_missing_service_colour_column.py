# Repairs production databases where busstops_service.colour_id is missing
# even though 0001_initial defines Service.colour as a ForeignKey. The model
# and migration history have always been correct; some databases just never
# got the column (schema drift). This is written defensively so it is a
# no-op wherever the column already exists.

from django.db import migrations


def add_colour_id_if_missing(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=%s AND column_name=%s",
            ["busstops_service", "colour_id"],
        )
        if cursor.fetchone():
            return
        cursor.execute(
            'ALTER TABLE "busstops_service" ADD COLUMN "colour_id" integer NULL '
            'CONSTRAINT "busstops_service_colour_id_fk_busstops_servicecolour_id" '
            'REFERENCES "busstops_servicecolour" ("id") '
            "DEFERRABLE INITIALLY DEFERRED"
        )
        cursor.execute(
            'CREATE INDEX "busstops_service_colour_id_idx" '
            'ON "busstops_service" ("colour_id")'
        )


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0063_governmentauthority_operator_government_authority"),
    ]

    operations = [
        migrations.RunPython(add_colour_id_if_missing, migrations.RunPython.noop),
    ]
