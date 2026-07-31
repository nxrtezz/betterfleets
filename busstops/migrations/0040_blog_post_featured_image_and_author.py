from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0035_blog_posts_and_operator_vehicle_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="blogpost",
            name="featured_image",
            field=models.ImageField(blank=True, null=True, upload_to="blog"),
        ),
        migrations.AddField(
            model_name="blogpost",
            name="author",
            field=models.ForeignKey(
                null=True,
                on_delete=models.SET_NULL,
                to="accounts.user",
            ),
        ),
    ]
