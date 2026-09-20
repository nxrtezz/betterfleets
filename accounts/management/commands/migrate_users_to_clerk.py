import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Create Clerk users for existing accounts and store their Clerk IDs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Create users and update the local database. Without this flag, only preview.",
        )

    def handle(self, *args, **options):
        if not settings.CLERK_SECRET_KEY:
            raise CommandError("CLERK_SECRET_KEY is required")

        users = User.objects.filter(clerk_user_id__isnull=True).exclude(email="")
        self.stdout.write(f"{users.count()} users are eligible for migration.")
        if not options["execute"]:
            self.stdout.write("Dry run only. Re-run with --execute to migrate users.")
            return

        headers = {
            "Authorization": f"Bearer {settings.CLERK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        for user in users.iterator():
            response = requests.post(
                "https://api.clerk.com/v1/users",
                headers=headers,
                json={
                    "external_id": str(user.pk),
                    "email_address": [user.email],
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "skip_password_requirement": True,
                    "public_metadata": {"legacy_user_id": user.pk},
                },
                timeout=30,
            )
            if not response.ok:
                raise CommandError(
                    f"Clerk rejected {user.email}: {response.status_code} {response.text}"
                )
            user.clerk_user_id = response.json()["id"]
            user.save(update_fields=["clerk_user_id"])
            self.stdout.write(f"Migrated {user.email}")
