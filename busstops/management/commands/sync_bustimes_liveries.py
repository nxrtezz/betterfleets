from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text
from vehicles.models import Livery


class Command(BaseCommand):
    help = "Import all liveries from bustimes.org/api/livery - field by field"

    def handle(self, *args, **options):
        client = BustimesApiClient()
        self.stdout.write("Importing liveries from bustimes.org/api/livery...")

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
                # Get external_id
                external_id = compact_text(item.get("id")) or None

                # Get ALL fields from the API item
                name = compact_text(item.get("name"))
                livery_type = compact_text(item.get("livery_type") or "css")
                colour = compact_text(item.get("colour"))
                colours = compact_text(item.get("colours"))
                angle = item.get("angle")
                horizontal = bool(item.get("horizontal", False))
                text_colour = compact_text(item.get("text_colour"))
                white_text = bool(item.get("white_text", False))
                stroke_colour = compact_text(item.get("stroke_colour"))
                left_css = compact_text(item.get("left_css"))
                right_css = compact_text(item.get("right_css"))
                show_name = bool(item.get("show_name", True))
                published = bool(item.get("published", True))
                slug = compact_text(item.get("slug"))

                # Try to find existing livery by external_id or name
                livery = None
                if external_id:
                    livery = Livery.objects.filter(external_id=external_id).first()
                if not livery and name:
                    livery = Livery.objects.filter(name__iexact=name).first()

                # Build values dict
                values = {
                    "name": name,
                    "livery_type": livery_type,
                    "colour": colour,
                    "colours": colours,
                    "angle": angle,
                    "horizontal": horizontal,
                    "text_colour": text_colour,
                    "white_text": white_text,
                    "stroke_colour": stroke_colour,
                    "left_css": left_css,
                    "right_css": right_css,
                    "show_name": show_name,
                    "published": published,
                }

                if external_id:
                    values["external_id"] = external_id
                if slug:
                    values["slug"] = slug

                if livery:
                    # Update ALL fields
                    for field, value in values.items():
                        if value is not None:
                            setattr(livery, field, value)
                    livery.save()
                    updated += 1
                else:
                    # Create new livery with ALL fields
                    livery = Livery.objects.create(**values)
                    created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing livery: {e}"))
                continue

        self.stdout.write(
            f"Liveries import complete: {created} created, {updated} updated"
        )
