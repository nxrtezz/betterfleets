from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("busstops", "0047_preservationgroup_verbose_names"),
        ("vehicles", "0054_vehicle_year_of_manufacture"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="preservation_group",
            field=models.ForeignKey(
                blank=True,
                help_text="Preservation group that owns this vehicle.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="preserved_vehicles",
                to="busstops.preservationgroup",
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="preserved_by_user",
            field=models.ForeignKey(
                blank=True,
                help_text="Individual user who preserves this vehicle.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="preserved_vehicles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="vehicle",
            constraint=models.CheckConstraint(
                condition=(
                    Q(("preserved_by_user__isnull", True))
                    | Q(("preservation_group__isnull", True))
                ),
                name="vehicle_single_preservation_owner",
            ),
        ),
    ]
