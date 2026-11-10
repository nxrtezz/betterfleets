from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0030_alter_outofservicetrackingcode_operator"),
    ]

    operations = [
        migrations.AddField(
            model_name="stoppoint",
            name="tiploc",
            field=models.CharField(
                blank=True,
                help_text="National Rail TIPLOC code from NaPTAN AnnotatedRailRef",
                max_length=16,
                null=True,
                verbose_name="TIPLOC",
            ),
        ),
        migrations.AddField(
            model_name="stoppoint",
            name="crs",
            field=models.CharField(
                blank=True,
                help_text="National Rail CRS station code",
                max_length=3,
                null=True,
            ),
        ),
    ]
