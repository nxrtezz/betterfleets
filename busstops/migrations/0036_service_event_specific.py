from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0035_blog_posts_and_operator_vehicle_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="event_specific",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
