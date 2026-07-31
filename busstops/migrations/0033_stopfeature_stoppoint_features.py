from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0032_svg_logo_support"),
    ]

    operations = [
        migrations.CreateModel(
            name="StopFeature",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "category",
                    models.CharField(
                        choices=[("feature", "Feature"), ("accessibility", "Accessibility")],
                        default="feature",
                        max_length=20,
                    ),
                ),
            ],
            options={
                "ordering": ("category", "name"),
            },
        ),
        migrations.AddField(
            model_name="stoppoint",
            name="features",
            field=models.ManyToManyField(blank=True, to="busstops.stopfeature"),
        ),
    ]
