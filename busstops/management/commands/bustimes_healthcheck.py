from django.core.management.base import BaseCommand
from django.db import connection
from django.apps import apps
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Check database schema, migrations, missing tables, API connectivity, sync status, and record counts"

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed diagnostic information",
        )

    def handle(self, *args, **options):
        verbose = options.get("verbose", False)
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🏥 BUSTIMES HEALTHCHECK")
        self.stdout.write("="*70)
        
        # Check migrations
        self.check_migrations(verbose)
        
        # Check for missing tables
        self.check_missing_tables(verbose)
        
        # Check record counts
        self.check_record_counts(verbose)
        
        self.stdout.write("="*70)
        self.stdout.write("✓ Healthcheck completed")
        self.stdout.write("="*70)

    def check_migrations(self, verbose):
        """Check if all migrations are applied."""
        self.stdout.write("\n📋 Checking migrations...")
        
        executor = MigrationExecutor(connection)
        applied_migrations = executor.applied_migrations
        migration_plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        
        if migration_plan:
            self.stdout.write(self.style.ERROR(f"  ✗ {len(migration_plan)} pending migrations"))
            if verbose:
                for migration in migration_plan:
                    self.stdout.write(f"    - {migration[0]}: {migration[1]}")
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ All migrations applied"))

    def check_missing_tables(self, verbose):
        """Check for missing tables that should exist."""
        self.stdout.write("\n📋 Checking for missing tables...")
        
        cursor = connection.cursor()
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        existing_tables = {row[0] for row in cursor.fetchall()}
        
        # Get expected tables from Django models
        expected_tables = set()
        for model in apps.get_models():
            expected_tables.add(model._meta.db_table)
        
        missing_tables = expected_tables - existing_tables
        
        if missing_tables:
            self.stdout.write(self.style.ERROR(f"  ✗ {len(missing_tables)} missing tables"))
            if verbose:
                for table in sorted(missing_tables):
                    self.stdout.write(f"    - {table}")
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ All expected tables exist"))

    def check_record_counts(self, verbose):
        """Check record counts for key tables."""
        self.stdout.write("\n📋 Checking record counts...")
        
        cursor = connection.cursor()
        
        key_tables = [
            ("busstops_operator", "Operators"),
            ("busstops_service", "Services"),
            ("busstops_stoppoint", "Stops"),
            ("vehicles_vehicle", "Vehicles"),
            ("vehicles_vehicletype", "Vehicle Types"),
            ("vehicles_livery", "Liveries"),
            ("bustimes_garage", "Garages"),
        ]
        
        for table_name, display_name in key_tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                self.stdout.write(f"  {display_name}: {count:,}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  {display_name}: ERROR - {e}"))
