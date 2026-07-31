from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0052_busgroup"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehicle",
            name="dvla_tax_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Not Taxed for on Road Use", "Not Taxed for on Road Use"),
                    ("SORN", "SORN"),
                    ("Taxed", "Taxed"),
                    ("Untaxed", "Untaxed"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="dvla_mot_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("No details held by DVLA", "No details held by DVLA"),
                    ("No results returned", "No results returned"),
                    ("Not valid", "Not valid"),
                    ("Valid", "Valid"),
                ],
                max_length=32,
            ),
        ),
    ]
