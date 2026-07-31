from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0017_operatorgroup_profile_operatorgroupdepot"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="accent_colour",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="organisation",
            name="banner",
            field=models.ImageField(blank=True, null=True, upload_to="organisations/banners"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="button_background",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="organisation",
            name="button_foreground",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="organisation",
            name="card_background",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="organisation",
            name="custom_css",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name="organisation",
            name="header_background",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="organisation",
            name="header_foreground",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="organisation",
            name="legal_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="organisation",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="organisations/logos"),
        ),
        migrations.AddField(
            model_name="organisation",
            name="phone",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="organisation",
            name="short_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="organisation",
            name="slogan",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_bluesky",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_fb",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_instagram",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_linkedin",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_mastodon",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_other",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_threads",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_tiktok",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_x",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="social_youtube",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="organisation",
            name="website",
            field=models.URLField(blank=True),
        ),
    ]
