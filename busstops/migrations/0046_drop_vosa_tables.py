# Generated migration to drop VOSA tables

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0043_rename_busstops_bu_object__7259f3_idx_busstops_bu_object__fff346_idx_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS vosa_registration CASCADE;",
            reverse_sql="",
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS vosa_licence CASCADE;",
            reverse_sql="",
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS vosa_variation CASCADE;",
            reverse_sql="",
        ),
    ]
