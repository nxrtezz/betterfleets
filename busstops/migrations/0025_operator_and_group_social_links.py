from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0024_operator_accurate_as_of"),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="social_bluesky",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operator",
            name="social_instagram",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operator",
            name="social_linkedin",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operator",
            name="social_mastodon",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operator",
            name="social_threads",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operator",
            name="social_tiktok",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operator",
            name="social_youtube",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_bluesky",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_linkedin",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_mastodon",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_threads",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_tiktok",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_youtube",
            field=models.URLField(blank=True),
        ),
    ]
