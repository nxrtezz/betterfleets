from django.db import transaction

from busstops.bustimes_sync import apply_sync_fields, compact_text
from busstops.models import BustimesSyncState
from vehicles.models import Livery, Vehicle, VehicleRevision

from ._sync_bustimes import BustimesSyncCommand, api_id, normalise_bustimes_livery


class Command(BustimesSyncCommand):
    help = "Sync liveries from the Bustimes API."
    endpoint = "liveries/"

    def find_livery(self, item):
        livery_data = normalise_bustimes_livery(item)
        external_id = api_id(item)
        state = BustimesSyncState.objects.filter(
            object_type="livery", external_id=external_id, local_model="vehicles.livery"
        ).first()
        if state and state.local_pk:
            livery = Livery.objects.filter(pk=state.local_pk).first()
            if livery:
                return livery

        name = livery_data["name"]
        if name:
            livery = Livery.objects.filter(name__iexact=name).first()
            if livery:
                return livery

        colours = compact_text(item.get("colours"))
        left_css = livery_data["left_css"]
        right_css = livery_data["right_css"]
        if colours or left_css:
            filters = {
                "colours": colours,
                "left_css": left_css,
                "right_css": right_css,
            }
            if name:
                filters["name__iexact"] = name
            return Livery.objects.filter(**filters).first()

    def values_from_item(self, item):
        livery_data = normalise_bustimes_livery(item)
        values = {
            "name": livery_data["name"] or compact_text(item.get("slug")),
            "show_name": item.get("show_name", not livery_data["anonymous_css"]),
            "colour": livery_data["colour"] or "#cccccc",
            "colours": compact_text(item.get("colours")),
            "angle": item.get("angle"),
            "horizontal": bool(item.get("horizontal", False)),
            "text_colour": compact_text(item.get("text_colour")),
            "white_text": bool(item.get("white_text", False)),
            "stroke_colour": compact_text(item.get("stroke_colour")),
            "left_css": livery_data["left_css"],
            "right_css": livery_data["right_css"],
            "published": bool(item.get("published", True)),
        }
        return {key: value for key, value in values.items() if value not in (None, "")}

    @transaction.atomic
    def deduplicate(self):
        merged = 0
        for livery in Livery.objects.order_by("id"):
            duplicates = Livery.objects.filter(
                name__iexact=livery.name,
                colours=livery.colours,
                left_css=livery.left_css,
                right_css=livery.right_css,
            ).exclude(pk=livery.pk)
            for duplicate in duplicates:
                Vehicle.objects.filter(livery=duplicate).update(livery=livery)
                VehicleRevision.objects.filter(from_livery=duplicate).update(from_livery=livery)
                VehicleRevision.objects.filter(to_livery=duplicate).update(to_livery=livery)
                duplicate.delete()
                merged += 1
        return merged

    def handle(self, *args, **options):
        created = updated = skipped = 0
        progress = self.progress(options)
        for item in self.iter_items_with_progress(options, progress):
            livery = self.find_livery(item) or Livery()
            result = apply_sync_fields(
                instance=livery,
                object_type="livery",
                external_id=api_id(item),
                values=self.values_from_item(item),
                payload=item,
                dry_run=options["dry_run"],
                force=options["force"],
            )
            created += int(result.created)
            updated += int(result.updated)
            skipped += len(result.skipped_fields)
            progress.tick(
                created=result.created,
                updated=result.updated,
                skipped=len(result.skipped_fields),
            )

        if not options["dry_run"]:
            skipped += self.deduplicate()
        self.print_summary(created, updated, skipped)
