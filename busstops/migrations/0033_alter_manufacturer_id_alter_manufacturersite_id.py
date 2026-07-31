from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0032_svg_logo_support"),
    ]

    operations = [
        migrations.AlterField(
            model_name="manufacturer",
            name="id",
            field=models.SlugField(max_length=48, primary_key=True, serialize=False),
        ),
        migrations.AlterField(
            model_name="manufacturersite",
            name="id",
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
    ]
