import django.db.models.deletion
from django.db import migrations, models

import disruptions.models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0027_bustimes_sync_state_stop_groups"),
        ("disruptions", "0009_situation_manual_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="situation",
            name="source",
            field=models.ForeignKey(
                default=disruptions.models.get_default_situation_source_pk,
                limit_choices_to={
                    "name__in": (
                        "bustimes.org",
                        "TfL",
                        "TfL disruptions",
                        "TfL statuses",
                        "BODS disruptions",
                        "BODS cancellations",
                        "Bus Open Data",
                        "Translink",
                    )
                },
                on_delete=django.db.models.deletion.CASCADE,
                to="busstops.datasource",
            ),
        ),
    ]
