import django.db.models.deletion
from django.contrib.gis.db import models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0020_operator_organisation"),
        ("busstops", "0020_alter_operatorgroup_options_operator_organisation_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Depot",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("location", models.PointField()),
                (
                    "operator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="busstops.operator",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
    ]
