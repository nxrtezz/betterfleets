from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0039_livery_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="livery",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="liveries"),
        ),
        migrations.AddField(
            model_name="livery",
            name="model_differences",
            field=models.TextField(blank=True),
        ),
    ]
