from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("photos", "0002_add_flickr_url"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE photos_photo "
                        "ADD COLUMN IF NOT EXISTS author varchar(255) NULL;"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    sql="ALTER TABLE photos_photo ALTER COLUMN author DROP NOT NULL;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="photo",
                    name="author",
                    field=models.CharField(blank=True, max_length=255, null=True),
                ),
            ],
        ),
    ]
