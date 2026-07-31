from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0022_ensure_depot_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="preserved",
            field=models.BooleanField(
                default=False,
                help_text="Tick for discontinued/preserved fleets (e.g. historic brands).",
            ),
        ),
        migrations.AddField(
            model_name="operator",
            name="ceased_operations_on",
            field=models.DateField(
                blank=True,
                help_text="If preserved, the date this operator ceased operations.",
                null=True,
            ),
        ),
    ]

