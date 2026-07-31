from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0048_review_moderation"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="vehiclereview",
            options={
                "ordering": ("-updated_at", "-created_at"),
                "permissions": [("delete_review", "Can delete review")],
            },
        ),
    ]
