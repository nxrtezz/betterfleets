from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0033_stopfeature_stoppoint_features"),
    ]

    operations = [
        migrations.AddField(
            model_name="routenotice",
            name="other_services",
            field=models.ManyToManyField(
                blank=True,
                related_name="related_route_notices",
                to="busstops.service",
            ),
        ),
    ]
