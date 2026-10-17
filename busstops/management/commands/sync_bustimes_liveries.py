from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text, apply_sync_fields
from vehicles.models import Livery
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Import all liveries from bustimes.org/api/livery - field by field"

    def handle(self, *args, **options):
        client = BustimesApiClient()
        self.stdout.write("Importing liveries from bustimes.org/api/livery...")

        # Get admin user for data change logs
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            self.stdout.write(self.style.WARNING("No admin user found, data changes will not be attributed"))
            admin_user = None

        created = updated = 0

        liveries_data = list(client.iter_results("liveries/"))

        self.stdout.write(f"Fetched {len(liveries_data)} liveries from API")

        if not liveries_data:
            self.stdout.write(self.style.WARNING("No liveries returned from API"))
            return

        progress = tqdm(
            liveries_data,
            desc="Processing liveries",
            unit="livery",
            file=self.stdout,
            disable=not liveries_data,
        )

        for item in progress:
            try:
                # Get fields from ACTUAL API response
                external_id = item.get("id")
                name = compact_text(item.get("name"))
                left_css = compact_text(item.get("left_css"))
                right_css = compact_text(item.get("right_css"))
                white_text = bool(item.get("white_text", False))
                text_colour = compact_text(item.get("text_colour"))
                stroke_colour = compact_text(item.get("stroke_colour"))

                # Try to find existing livery by external_id or name
                livery = None
                if external_id:
                    livery = Livery.objects.filter(external_id=str(external_id)).first()
                if not livery and name:
                    livery = Livery.objects.filter(name__iexact=name).first()

                # Build values dict based on ACTUAL API fields
                values = {
                    "name": name,
                    "livery_type": "css",  # API provides CSS gradients
                    "left_css": left_css,
                    "right_css": right_css,
                    "white_text": white_text,
                }

                if text_colour:
                    values["text_colour"] = text_colour
                if stroke_colour:
                    values["stroke_colour"] = stroke_colour
                if external_id:
                    values["external_id"] = str(external_id)

                # Remove None values
                values = {k: v for k, v in values.items() if v is not None}

                if livery:
                    # Update using apply_sync_fields with admin user
                    result = apply_sync_fields(
                        instance=livery,
                        object_type="livery",
                        external_id=str(external_id) if external_id else name,
                        values=values,
                        payload=item,
                        dry_run=False,
                        force=True,
                        source="bustimes_sync:livery",
                        user=admin_user,
                    )
                    if result.created:
                        created += 1
                    if result.updated:
                        updated += 1
                else:
                    # Create new livery
                    livery = Livery()
                    for field, value in values.items():
                        setattr(livery, field, value)
                    livery.save()
                    created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing livery: {e}"))
                continue

        self.stdout.write(
            f"Liveries import complete: {created} created, {updated} updated"
        )
