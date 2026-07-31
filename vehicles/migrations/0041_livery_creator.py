from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0040_livery_wiki_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="livery",
            name="creator",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
