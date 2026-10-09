# Generated manually to fix gearbox column that wasn't properly migrated

from django.db import migrations, models
import django.db.models.deletion


def fix_gearbox_column(apps, schema_editor):
    """Fix the gearbox column by dropping the old one and adding the proper ForeignKey."""
    Vehicle = apps.get_model('vehicles', 'Vehicle')
    with schema_editor.connection.cursor() as cursor:
        # Map field names to their actual table names
        field_table_map = {
            'chassis': 'vehicles_chassis',
            'engine': 'vehicles_engine',
            'emissions_rating': 'vehicles_emissionsrating',
            'gearbox': 'vehicles_gearbox',
        }
        
        # Also check and fix chassis, engine, emissions_rating, and gearbox columns if needed
        for field, table_name in field_table_map.items():
            fk_column = f'{field}_id'
            
            # Check if the old CharField column exists
            cursor.execute(f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'vehicles_vehicle'
                AND column_name = '{field}'
            """)
            result = cursor.fetchone()
            
            if result and result[1] != 'integer':
                # Old CharField column exists, drop it
                cursor.execute(f'ALTER TABLE vehicles_vehicle DROP COLUMN IF EXISTS {field}')
            
            # Check if the ForeignKey column exists
            cursor.execute(f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'vehicles_vehicle'
                AND column_name = '{fk_column}'
            """)
            fk_result = cursor.fetchone()
            
            if fk_result is None:
                # ForeignKey column doesn't exist, add it
                cursor.execute(f'''
                    ALTER TABLE vehicles_vehicle
                    ADD COLUMN {fk_column} integer NULL
                    REFERENCES {table_name}(id) ON DELETE SET NULL
                ''')


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0115_create_missing_tables'),
    ]

    operations = [
        migrations.RunPython(fix_gearbox_column, migrations.RunPython.noop),
    ]
