from django.core.management.base import BaseCommand, CommandError
from busstops.models import Operator


class Command(BaseCommand):
    help = "Delete fleet list notes for a specific operator"

    def add_arguments(self, parser):
        parser.add_argument("noc", help="Operator NOC code (e.g., FHAM)")

    def handle(self, *args, **options):
        noc = options["noc"].strip().upper()
        
        try:
            operator = Operator.objects.get(noc=noc)
        except Operator.DoesNotExist:
            raise CommandError(f"Operator with NOC '{noc}' does not exist")
        
        if not operator.fleet_list_notes:
            self.stdout.write(self.style.WARNING(f"Operator {noc} has no fleet list notes to delete"))
            return
        
        old_notes = operator.fleet_list_notes
        operator.fleet_list_notes = ""
        operator.save(update_fields=["fleet_list_notes"])
        
        self.stdout.write(
            self.style.SUCCESS(f"Deleted fleet list notes for operator {noc} ({operator.name})")
        )
        self.stdout.write(f"Old notes: {old_notes[:200]}{'...' if len(old_notes) > 200 else ''}")
