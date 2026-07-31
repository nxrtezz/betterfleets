from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0018_organisation_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="accent_colour",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operator",
            name="button_background",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operator",
            name="button_foreground",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operator",
            name="card_background",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operator",
            name="custom_css",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="operator",
            name="header_background",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operator",
            name="header_foreground",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]