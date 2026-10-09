from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0103_drop_orphan_column_not_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="first_tracked_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this vehicle was first observed in live tracking.",
                null=True,
            ),
        ),
    ]
