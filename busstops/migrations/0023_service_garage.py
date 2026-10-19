import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0022_ticket_models"),
        ("bustimes", "0028_garage_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="garage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                to="bustimes.garage",
            ),
        ),
    ]
