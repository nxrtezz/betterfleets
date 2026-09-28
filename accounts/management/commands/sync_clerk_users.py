import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Sync existing Clerk users to Django database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Create users in Django. Without this flag, only preview.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of users to sync (default: 100)",
        )

    def handle(self, *args, **options):
        if not settings.CLERK_SECRET_KEY:
            raise CommandError("CLERK_SECRET_KEY is required")

        headers = {
            "Authorization": f"Bearer {settings.CLERK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        # Fetch users from Clerk
        self.stdout.write("Fetching users from Clerk...")
        response = requests.get(
            "https://api.clerk.com/v1/users",
            headers=headers,
            params={"limit": options["limit"]},
            timeout=30,
        )

        if not response.ok:
            raise CommandError(
                f"Failed to fetch Clerk users: {response.status_code} {response.text}"
            )

        clerk_users = response.json()
        total_count = clerk_users.get("total_count", 0)
        users_data = clerk_users.get("data", [])

        self.stdout.write(f"Found {total_count} total users in Clerk")
        self.stdout.write(f"Processing {len(users_data)} users (limit: {options['limit']})")

        # Find users that need to be synced
        users_to_create = []
        users_to_update = []

        for clerk_user in users_data:
            clerk_user_id = clerk_user.get("id")
            email_addresses = clerk_user.get("email_addresses", [])
            primary_email = None

            # Find primary email
            for email_obj in email_addresses:
                if email_obj.get("verified", False):
                    primary_email = email_obj.get("email_address")
                    break

            if not primary_email and email_addresses:
                primary_email = email_addresses[0].get("email_address")

            if not primary_email:
                self.stdout.write(
                    self.style.WARNING(f"Skipping user {clerk_user_id}: no email found")
                )
                continue

            # Check if user exists in Django
            django_user = User.objects.filter(clerk_user_id=clerk_user_id).first()

            if django_user:
                # User exists, check if update needed
                if django_user.email != primary_email:
                    users_to_update.append(
                        {
                            "django_user": django_user,
                            "clerk_user": clerk_user,
                            "primary_email": primary_email,
                        }
                    )
            else:
                # User doesn't exist, needs to be created
                users_to_create.append(
                    {
                        "clerk_user": clerk_user,
                        "primary_email": primary_email,
                    }
                )

        self.stdout.write(
            f"Users to create: {len(users_to_create)}, Users to update: {len(users_to_update)}"
        )

        if not options["execute"]:
            self.stdout.write("Dry run only. Re-run with --execute to sync users.")
            return

        # Create users
        for user_data in users_to_create:
            clerk_user = user_data["clerk_user"]
            primary_email = user_data["primary_email"]

            first_name = clerk_user.get("first_name", "")
            last_name = clerk_user.get("last_name", "")
            username = primary_email.split("@")[0]
            clerk_user_id = clerk_user.get("id")

            try:
                # Check if user exists by email (for edge case where email exists but no clerk_user_id)
                existing_user = User.objects.filter(email=primary_email).first()
                if existing_user:
                    self.stdout.write(
                        f"Updating existing user {primary_email} with clerk_user_id"
                    )
                    existing_user.clerk_user_id = clerk_user_id
                    existing_user.save(update_fields=["clerk_user_id"])
                else:
                    user = User.objects.create_user(
                        username=username,
                        email=primary_email,
                        first_name=first_name,
                        last_name=last_name,
                        clerk_user_id=clerk_user_id,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"Created user: {primary_email} ({clerk_user_id})")
                    )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to create user {primary_email}: {e}")
                )

        # Update users
        for user_data in users_to_update:
            django_user = user_data["django_user"]
            clerk_user = user_data["clerk_user"]
            primary_email = user_data["primary_email"]

            try:
                django_user.email = primary_email
                django_user.username = primary_email.split("@")[0]
                django_user.first_name = clerk_user.get("first_name", "")
                django_user.last_name = clerk_user.get("last_name", "")
                django_user.save()
                self.stdout.write(
                    self.style.SUCCESS(f"Updated user: {primary_email}")
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to update user {primary_email}: {e}")
                )

        self.stdout.write(self.style.SUCCESS("User sync completed"))
