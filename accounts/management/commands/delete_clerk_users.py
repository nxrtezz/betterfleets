from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Delete all Django users that have a clerk_user_id (Clerk accounts)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion without prompting',
        )

    def handle(self, *args, **options):
        # Find all users with clerk_user_id
        clerk_users = User.objects.filter(clerk_user_id__isnull=False).exclude(clerk_user_id='')

        count = clerk_users.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No Clerk users found"))
            return

        self.stdout.write(f"Found {count} Clerk users")
        self.stdout.write("These users will be PERMANENTLY DELETED")

        if not options['confirm']:
            response = input("Are you sure you want to delete all Clerk users? Type 'yes' to confirm: ")
            if response.lower() != 'yes':
                self.stdout.write(self.style.WARNING("Cancelled"))
                return

        # Delete all Clerk users
        deleted_count, _ = clerk_users.delete()

        self.stdout.write(
            self.style.SUCCESS(f"Successfully deleted {deleted_count} Clerk users")
        )
