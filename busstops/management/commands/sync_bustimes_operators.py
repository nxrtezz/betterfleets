from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text, apply_sync_fields, api_id
from busstops.models import Operator
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Import all operators from bustimes.org/api/operator - field by field"

    def handle(self, *args, **options):
        client = BustimesApiClient()
        self.stdout.write("Importing operators from bustimes.org/api/operator...")

        # Get admin user for data change logs
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            self.stdout.write(self.style.WARNING("No admin user found, data changes will not be attributed"))
            admin_user = None

        created = updated = 0

        operators_data = list(client.iter_results("operators/"))

        self.stdout.write(f"Fetched {len(operators_data)} operators from API")

        if not operators_data:
            self.stdout.write(self.style.WARNING("No operators returned from API"))
            return

        progress = tqdm(
            operators_data,
            desc="Processing operators",
            unit="operator",
            file=self.stdout,
            disable=not operators_data,
        )

        for item in progress:
            try:
                # Get fields from ACTUAL API response
                noc = compact_text(item.get("noc"))
                slug = compact_text(item.get("slug"))
                name = compact_text(item.get("name"))
                aka = compact_text(item.get("aka"))
                vehicle_mode = compact_text(item.get("vehicle_mode"))
                region_id = item.get("region_id")
                url = compact_text(item.get("url"))
                twitter = compact_text(item.get("twitter"))

                if not noc:
                    self.stdout.write(f"Skipping item with no noc: {item}")
                    continue

                # Try to find existing operator by noc
                operator = Operator.objects.filter(noc=noc).first()

                # Build values dict based on ACTUAL API fields
                values = {
                    "name": name or noc,
                    "slug": slug,
                    "aka": aka,
                    "vehicle_mode": vehicle_mode,
                }

                if region_id:
                    values["region_id"] = region_id
                if url:
                    values["url"] = url
                if twitter:
                    values["twitter"] = twitter

                # Remove None values
                values = {k: v for k, v in values.items() if v is not None}

                if operator:
                    # Update using apply_sync_fields with admin user
                    result = apply_sync_fields(
                        instance=operator,
                        object_type="operator",
                        external_id=noc,
                        values=values,
                        payload=item,
                        dry_run=False,
                        force=True,
                        source="bustimes_sync:operator",
                        user=admin_user,
                    )
                    if result.created:
                        created += 1
                    if result.updated:
                        updated += 1
                else:
                    # Create new operator
                    operator = Operator()
                    for field, value in values.items():
                        setattr(operator, field, value)
                    operator.save()
                    created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing operator: {e}"))
                continue

        self.stdout.write(
            f"Operators import complete: {created} created, {updated} updated"
        )
