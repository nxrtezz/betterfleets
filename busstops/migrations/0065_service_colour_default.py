from django.db import migrations, models


def fix_service_colour_null_constraint(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    with connection.cursor() as cursor:
        # Update any NULL values to empty string
        cursor.execute(
            "UPDATE busstops_service SET colour = '' WHERE colour IS NULL"
        )
        # Make column nullable
        cursor.execute(
            "ALTER TABLE busstops_service ALTER COLUMN colour DROP NOT NULL"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0064_service_colour_hex"),
    ]

    operations = [
        # First fix the database constraint
        migrations.RunPython(fix_service_colour_null_constraint, migrations.RunPython.noop),
        # Then update the model definition to match
        migrations.AlterField(
            model_name='service',
            name='colour',
            field=models.CharField(
                blank=True,
                null=True,
                help_text='Hex colour code e.g. #0055aa',
                max_length=7
            ),
        ),
    ]
