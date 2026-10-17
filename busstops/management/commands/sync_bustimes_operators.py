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
                # Get ALL fields from the API item
                noc = compact_text(item.get("noc") or item.get("id") or item.get("code"))
                name = compact_text(item.get("name"))
                external_id = api_id(item)
                qualifier_name = compact_text(item.get("qualifier_name"))
                aka = compact_text(item.get("aka"))
                slogan = compact_text(item.get("slogan"))
                vehicle_mode = compact_text(item.get("vehicle_mode"))
                social_x = compact_text(item.get("social_x"))
                social_fb = compact_text(item.get("social_fb"))
                social_instagram = compact_text(item.get("social_instagram"))
                social_linkedin = compact_text(item.get("social_linkedin"))
                social_youtube = compact_text(item.get("social_youtube"))
                social_tiktok = compact_text(item.get("social_tiktok"))
                social_threads = compact_text(item.get("social_threads"))
                social_bluesky = compact_text(item.get("social_bluesky"))
                social_mastodon = compact_text(item.get("social_mastodon"))
                social_other = compact_text(item.get("social_other"))
                header_background = compact_text(item.get("header_background"))
                header_foreground = compact_text(item.get("header_foreground"))
                accent_colour = compact_text(item.get("accent_colour"))
                card_background = compact_text(item.get("card_background"))
                button_background = compact_text(item.get("button_background"))
                button_foreground = compact_text(item.get("button_foreground"))
                custom_css = compact_text(item.get("custom_css"))

                if not noc:
                    self.stdout.write(f"Skipping item with no noc: {item}")
                    continue

                # Try to find existing operator by noc
                operator = Operator.objects.filter(noc=noc).first()

                # Build values dict
                values = {
                    "name": name or noc,
                    "qualifier_name": qualifier_name,
                    "aka": aka,
                    "slogan": slogan,
                    "vehicle_mode": vehicle_mode,
                    "social_x": social_x,
                    "social_fb": social_fb,
                    "social_instagram": social_instagram,
                    "social_linkedin": social_linkedin,
                    "social_youtube": social_youtube,
                    "social_tiktok": social_tiktok,
                    "social_threads": social_threads,
                    "social_bluesky": social_bluesky,
                    "social_mastodon": social_mastodon,
                    "social_other": social_other,
                    "header_background": header_background,
                    "header_foreground": header_foreground,
                    "accent_colour": accent_colour,
                    "card_background": card_background,
                    "button_background": button_background,
                    "button_foreground": button_foreground,
                    "custom_css": custom_css,
                }

                if external_id:
                    values["external_id"] = external_id

                # Remove None values
                values = {k: v for k, v in values.items() if v is not None}

                if operator:
                    # Update using apply_sync_fields with admin user
                    result = apply_sync_fields(
                        instance=operator,
                        object_type="operator",
                        external_id=external_id or noc,
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
