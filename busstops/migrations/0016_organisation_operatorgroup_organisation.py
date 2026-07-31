from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0015_homepagenotice"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organisation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("slug", models.SlugField(max_length=48, unique=True)),
                ("name", models.CharField(max_length=100)),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="organisation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                to="busstops.organisation",
            ),
        ),
    ]
