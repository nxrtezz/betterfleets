# Repairs production databases where the vehicles_advancedfield table was
# never created, even though 0050_advanced_field defines the model. Written
# defensively (CREATE TABLE IF NOT EXISTS) so it is a no-op wherever the
# table already exists.

from django.db import migrations


def create_advancedfield_table_if_missing(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS \"vehicles_advancedfield\" ("
            '"id" serial NOT NULL PRIMARY KEY, '
            '"name" varchar(255) NOT NULL UNIQUE, '
            '"slug" varchar(255) NOT NULL UNIQUE, '
            '"field_type" varchar(20) NOT NULL, '
            '"help_text" varchar(500) NOT NULL DEFAULT \'\', '
            '"display_order" integer NOT NULL DEFAULT 0 '
            'CHECK ("display_order" >= 0)'
            ")"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0099_remove_busgroup_vehicles_and_add_dates"),
    ]

    operations = [
        migrations.RunPython(
            create_advancedfield_table_if_missing, migrations.RunPython.noop
        ),
    ]
