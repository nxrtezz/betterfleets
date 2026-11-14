import json
from django.core.management.base import BaseCommand
from vehicles.coverage import live_vehicle_payloads, operator_coverage

class Command(BaseCommand):
    help = "Audit live operator timetable coverage and actual journey/trip attachments"
    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--min-vehicles", type=int, default=10)
    def handle(self, *args, **options):
        rows = operator_coverage(live_vehicle_payloads())
        if options["json"]:
            self.stdout.write(json.dumps(rows))
            return
        self.stdout.write("NOC\tTRACKING\tSERVICES\tTRIPS\tLIVE WITH TRIP\tOPERATOR")
        for row in rows:
            if row["tracking"] >= options["min_vehicles"]:
                self.stdout.write(f'{row["noc"]}\t{row["tracking"]}\t{row["services"]}\t{row["trips"]}\t{row["live_with_trip"]}\t{row["name"]}')
