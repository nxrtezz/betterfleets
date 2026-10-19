from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bustimes", "0027_stoptime_stop_dep_covering_drop_condition"),
    ]

    operations = [
        migrations.AddField(
            model_name="garage",
            name="id",
            field=models.CharField(max_length=50, unique=True, primary_key=True, serialize=False),
            preserve_default=False,
        ),
    ]
