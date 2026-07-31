from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("fleet", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PinnedOperator",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    )
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "operator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pinned_by_users",
                        to="busstops.operator",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pinned_operators",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("created_at",),
                "verbose_name": "pinned operator",
                "verbose_name_plural": "pinned operators",
            },
        ),
        migrations.AddConstraint(
            model_name="pinnedoperator",
            constraint=models.UniqueConstraint(
                fields=("user", "operator"), name="fleet_unique_user_pinned_operator"
            ),
        ),
    ]
