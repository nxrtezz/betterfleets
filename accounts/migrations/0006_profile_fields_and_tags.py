from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_alter_registrationsettings_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfileTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True)),
                ("slug", models.SlugField(max_length=50, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("badge_background", models.CharField(default="#334155", max_length=7)),
                ("badge_text_colour", models.CharField(default="#ffffff", max_length=7)),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.AddField(
            model_name="user",
            name="discord_username",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="user",
            name="display_name",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="user",
            name="flickr_username",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="user",
            name="manual_tags",
            field=models.ManyToManyField(blank=True, related_name="users", to="accounts.profiletag"),
        ),
        migrations.AddField(
            model_name="user",
            name="profile_banner",
            field=models.ImageField(blank=True, null=True, upload_to="users/profile-banners"),
        ),
        migrations.AddField(
            model_name="user",
            name="profile_picture",
            field=models.ImageField(blank=True, null=True, upload_to="users/profile-pictures"),
        ),
    ]
