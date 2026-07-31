from django.db import migrations


def ensure_depot_table(apps, schema_editor):
    Depot = apps.get_model("busstops", "Depot")
    table_name = Depot._meta.db_table
    existing_tables = set(schema_editor.connection.introspection.table_names())
    if table_name in existing_tables:
        return
    schema_editor.create_model(Depot)


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0021_organisationdepot"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    ensure_depot_table,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[],
        ),
    ]
