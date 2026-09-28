from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bustimes", "0022_stoptime_display_name"),
    ]

    operations = [
        migrations.DeleteModel(name="SimulationConfig"),
    ]
