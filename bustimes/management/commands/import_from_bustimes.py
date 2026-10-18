from django.core.management.base import BaseCommand
from django.core.management import call_command

class Command(BaseCommand):
    help = "Import all data from bustimes.org (operators, vehicles, etc.)"

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("Importing data from bustimes.org")
        self.stdout.write("=" * 60)

        # 1. Import operators
        self.stdout.write("\n1. Importing operators...")
        call_command("import_bustimes_operators")

        # 2. Delete all services
        self.stdout.write("\n2. Deleting all services...")
        call_command("delete_all_services")

        # 3. Drop all vehicles, types, liveries
        self.stdout.write("\n3. Dropping all vehicles, types, and liveries...")
        call_command("drop_all_vehicles")

        # 4. Import vehicles (includes vehicle types and liveries)
        self.stdout.write("\n4. Importing vehicles...")
        call_command("import_bustimes_vehicles")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Import complete!")
        self.stdout.write("=" * 60)
