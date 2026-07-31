from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from busstops.models import DataSource

from disruptions.models import Situation, Link, ValidityPeriod, Consequence


class Command(BaseCommand):
    help = "Audit disruptions data to identify total, duplicates, expired, orphaned links, and failed imports"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix-expired",
            action="store_true",
            help="Automatically mark expired disruptions as not current",
        )
        parser.add_argument(
            "--fix-empty-data",
            action="store_true",
            help="Delete situations with empty data (potential failed imports)",
        )

    def handle(self, *args, **options):
        self.stdout.write("=" * 80)
        self.stdout.write("DISRUPTIONS AUDIT REPORT")
        self.stdout.write("=" * 80)
        self.stdout.write("")

        # Total disruptions
        total_situations = Situation.objects.count()
        current_situations = Situation.objects.filter(current=True).count()
        non_current_situations = Situation.objects.filter(current=False).count()
        
        self.stdout.write(f"Total disruptions: {total_situations}")
        self.stdout.write(f"  Current: {current_situations}")
        self.stdout.write(f"  Non-current: {non_current_situations}")
        self.stdout.write("")

        # Duplicate disruptions (by situation_number)
        duplicates = (
            Situation.objects.values("situation_number")
            .annotate(count=Count("id"))
            .filter(count__gt=1, situation_number__isnull=False)
            .order_by("-count")
        )
        
        self.stdout.write(f"Duplicate situation_numbers: {duplicates.count()}")
        if duplicates.exists():
            for dup in duplicates[:10]:  # Show first 10
                self.stdout.write(f"  {dup['situation_number']}: {dup['count']} occurrences")
            if duplicates.count() > 10:
                self.stdout.write(f"  ... and {duplicates.count() - 10} more")
        self.stdout.write("")

        # Expired disruptions (publication_window upper is in the past but current=True)
        now = timezone.now()
        expired_situations = Situation.objects.filter(
            current=True,
            publication_window__fully_lt=(None, now)
        )
        
        self.stdout.write(f"Expired disruptions (current=True but publication_window ended): {expired_situations.count()}")
        if expired_situations.exists():
            for situation in expired_situations[:5]:  # Show first 5
                self.stdout.write(f"  ID {situation.id}: {situation.situation_number} - {situation.summary[:50]}")
            if expired_situations.count() > 5:
                self.stdout.write(f"  ... and {expired_situations.count() - 5} more")
            
            # Fix expired disruptions if requested
            if options.get("fix_expired"):
                count = expired_situations.update(current=False)
                self.stdout.write(self.style.SUCCESS(f"  Fixed: Marked {count} expired disruptions as not current"))
        self.stdout.write("")

        # Orphaned links (links without valid situation - shouldn't happen due to FK, but check anyway)
        # Actually, due to CASCADE, links should be deleted when situation is deleted
        # So orphaned links would be None
        total_links = Link.objects.count()
        self.stdout.write(f"Total links: {total_links}")
        
        # Check for links with null situation (shouldn't exist due to FK constraint)
        orphaned_links = Link.objects.filter(situation__isnull=True).count()
        if orphaned_links > 0:
            self.stdout.write(self.style.WARNING(f"  WARNING: {orphaned_links} links with null situation"))
            # Delete orphaned links
            deleted_count = Link.objects.filter(situation__isnull=True).delete()[0]
            self.stdout.write(self.style.SUCCESS(f"  Fixed: Deleted {deleted_count} orphaned links"))
        else:
            self.stdout.write(f"  No orphaned links (all links have valid situations)")
        self.stdout.write("")

        # Check for situations without validity periods
        situations_without_validity = Situation.objects.filter(
            validityperiod__isnull=True
        ).count()
        self.stdout.write(f"Situations without validity periods: {situations_without_validity}")
        self.stdout.write("")

        # Check for situations without consequences
        situations_without_consequences = Situation.objects.filter(
            consequence__isnull=True
        ).count()
        self.stdout.write(f"Situations without consequences: {situations_without_consequences}")
        self.stdout.write("")

        # Check for situations with empty data (potential failed imports)
        situations_without_data = Situation.objects.filter(
            Q(data="") | Q(data__isnull=True)
        ).count()
        self.stdout.write(f"Situations without data (potential failed imports): {situations_without_data}")
        if situations_without_data > 0:
            for situation in Situation.objects.filter(
                Q(data="") | Q(data__isnull=True)
            )[:5]:
                self.stdout.write(f"  ID {situation.id}: {situation.situation_number} - source: {situation.source.name if situation.source else 'None'}")
            if situations_without_data > 5:
                self.stdout.write(f"  ... and {situations_without_data - 5} more")
            
            # Fix situations with empty data if requested
            if options.get("fix_empty_data"):
                deleted_count = Situation.objects.filter(
                    Q(data="") | Q(data__isnull=True)
                ).delete()[0]
                self.stdout.write(self.style.SUCCESS(f"  Fixed: Deleted {deleted_count} situations with empty data"))
        self.stdout.write("")

        # Check for situations without summary or text
        situations_without_summary_text = Situation.objects.filter(
            Q(summary="") | Q(summary__isnull=True),
            Q(text="") | Q(text__isnull=True)
        ).count()
        self.stdout.write(f"Situations without summary or text: {situations_without_summary_text}")
        self.stdout.write("")

        # Check by source
        self.stdout.write("Situations by source:")
        sources = DataSource.objects.filter(
            situation__isnull=False
        ).annotate(
            count=Count("situation")
        ).order_by("-count")
        
        for source in sources:
            current_count = Situation.objects.filter(source=source, current=True).count()
            self.stdout.write(f"  {source.name}: {source.count} total ({current_count} current)")
        self.stdout.write("")

        # Summary
        self.stdout.write("=" * 80)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Total disruptions: {total_situations}")
        self.stdout.write(f"Duplicate situation_numbers: {duplicates.count()}")
        self.stdout.write(f"Expired disruptions: {expired_situations.count()}")
        self.stdout.write(f"Orphaned links: {orphaned_links}")
        self.stdout.write(f"Situations without validity periods: {situations_without_validity}")
        self.stdout.write(f"Situations without consequences: {situations_without_consequences}")
        self.stdout.write(f"Situations without data (potential failed imports): {situations_without_data}")
        self.stdout.write(f"Situations without summary/text: {situations_without_summary_text}")
        self.stdout.write("=" * 80)
