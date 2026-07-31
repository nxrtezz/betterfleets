"""
Django management command to import ridden logs from TransitTracker.

Usage:
    python manage.py import_transittracker <transittracker_username> <local_username> [operator_nocs...]

Example:
    python manage.py import_transittracker Lm009 myuser BLUS BHBC
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from fleet.transittracker_scraper import run_import

User = get_user_model()


class Command(BaseCommand):
    help = 'Import ridden logs from TransitTracker user pages'

    def add_arguments(self, parser):
        parser.add_argument(
            'transittracker_username',
            type=str,
            help='TransitTracker username to scrape'
        )
        parser.add_argument(
            'local_username',
            type=str,
            help='Local username to create ride logs for'
        )
        parser.add_argument(
            'operator_nocs',
            nargs='+',
            type=str,
            help='Operator NOC codes to scrape (e.g., BLUS BHBC)'
        )
        parser.add_argument(
            '--datasource',
            type=str,
            default='BUSTIM',
            help='Data source (default: BUSTIM)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without actually creating records'
        )

    def handle(self, *args, **options):
        transittracker_username = options['transittracker_username']
        local_username = options['local_username']
        operator_nocs = options['operator_nocs']
        datasource = options['datasource']
        dry_run = options['dry_run']

        # Get the local user
        try:
            user = User.objects.get(username=local_username)
        except User.DoesNotExist:
            raise CommandError(f'User "{local_username}" does not exist')

        self.stdout.write(
            f'Importing from TransitTracker user "{transittracker_username}" '
            f'to local user "{local_username}"'
        )
        self.stdout.write(f'Operators: {", ".join(operator_nocs)}')
        self.stdout.write(f'Datasource: {datasource}')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No records will be created'))

        # Run the import
        try:
            results = run_import(
                transittracker_username=transittracker_username,
                user=user,
                operator_nocs=operator_nocs,
                datasource=datasource,
                dry_run=dry_run
            )

            # Display results
            self.stdout.write(self.style.SUCCESS('\nImport Results:'))
            self.stdout.write(f'  Operators scraped: {results["operators_scraped"]}')
            self.stdout.write(f'  Total vehicles found: {results["total_vehicles_found"]}')
            self.stdout.write(f'  Matched to database: {results["matched"]}')
            self.stdout.write(
                self.style.SUCCESS(f'  Ride logs created: {results["created"]}')
            )
            self.stdout.write(f'  Skipped: {results["skipped"]}')
            if results['errors']:
                self.stdout.write(self.style.ERROR(f'  Errors: {results["errors"]}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Import failed: {e}'))
            raise
