from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0044_alter_vehiclereview_rating"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="vehiclereview",
            name="unique_vehicle_review_per_user",
        ),
    ]
