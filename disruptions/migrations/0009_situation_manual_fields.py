from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0027_bustimes_sync_state_stop_groups"),
        ("disruptions", "0008_alter_situation_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="situation",
            name="affected_admin_areas",
            field=models.ManyToManyField(blank=True, to="busstops.adminarea"),
        ),
        migrations.AddField(
            model_name="situation",
            name="affected_operators",
            field=models.ManyToManyField(blank=True, to="busstops.operator"),
        ),
        migrations.AddField(
            model_name="situation",
            name="affected_services",
            field=models.ManyToManyField(blank=True, to="busstops.service"),
        ),
        migrations.AddField(
            model_name="situation",
            name="predicted_cause",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="situation",
            name="predicted_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
