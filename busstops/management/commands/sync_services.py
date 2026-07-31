import os

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from busstops.models import Service


class Command(BaseCommand):
    help = "Sync services from Bustimes API and import TNDS, Passenger, and BODS data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--operator",
            help="Operator NOC/code filter for service sync requests.",
        )
        parser.add_argument(
            "--tnds-username",
            help="TNDS FTP username for importing TNDS data.",
        )
        parser.add_argument(
            "--tnds-password",
            help="TNDS FTP password for importing TNDS data.",
        )
        parser.add_argument(
            "--bods-api-key",
            help="BODS API key for importing BODS data.",
        )
        parser.add_argument(
            "--skip-bustimes",
            action="store_true",
            help="Skip syncing services from Bustimes API.",
        )
        parser.add_argument(
            "--skip-tnds",
            action="store_true",
            help="Skip importing TNDS data.",
        )
        parser.add_argument(
            "--skip-passenger",
            action="store_true",
            help="Skip importing Passenger data.",
        )
        parser.add_argument(
            "--skip-bods",
            action="store_true",
            help="Skip importing BODS data.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without making changes.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force updates even if fields are protected.",
        )
        parser.add_argument(
            "--clean-slate",
            action="store_true",
            help="Delete all existing services for the operator before syncing.",
        )

    def get_existing_service_count(self, operator=None):
        """Get count of existing services before sync to detect duplicates"""
        queryset = Service.objects.filter(current=True)
        if operator:
            queryset = queryset.filter(operator__noc__iexact=operator)
        return queryset.count()

    def check_for_duplicates(self, operator=None):
        """Check for potential duplicate services based on service_code and line_name"""
        duplicates = Service.objects.filter(current=True).values(
            "service_code", "line_name"
        ).annotate(
            count=Count("id")
        ).filter(count__gt=1)
        
        if operator:
            duplicates = duplicates.filter(operator__noc__iexact=operator)
        
        return list(duplicates)

    def handle(self, *args, **options):
        from django.db.models import Count
        
        operator = options.get("operator")
        tnds_username = options.get("tnds_username") or os.environ.get("TNDS_USERNAME")
        tnds_password = options.get("tnds_password") or os.environ.get("TNDS_PASSWORD")
        bods_api_key = options.get("bods_api_key") or os.environ.get("BODS_API_KEY")
        skip_bustimes = options.get("skip_bustimes")
        skip_tnds = options.get("skip_tnds")
        skip_passenger = options.get("skip_passenger")
        skip_bods = options.get("skip_bods")
        dry_run = options.get("dry_run")
        force = options.get("force")
        clean_slate = options.get("clean_slate")

        self.stdout.write("Starting comprehensive service sync...")
        
        if operator:
            self.stdout.write(f"Filtering by operator: {operator}")

        # Clean slate: delete all existing services for the operator
        if clean_slate and operator:
            self.stdout.write(f"\n=== Clean Slate: Deleting all services for operator {operator} ===")
            if not dry_run:
                services_to_delete = Service.objects.filter(operator__noc__iexact=operator)
                count = services_to_delete.count()
                if count > 0:
                    self.stdout.write(f"Deleting {count} services...")
                    try:
                        services_to_delete.delete()
                        self.stdout.write(self.style.SUCCESS(f"Deleted {count} services"))
                    except Exception as e:
                        # If disruptions tables don't exist, delete without cascading through them
                        if "disruptions" in str(e):
                            self.stdout.write(self.style.WARNING("Disruptions tables missing, deleting without cascade"))
                            # Delete service codes first
                            from busstops.models import ServiceCode
                            ServiceCode.objects.filter(service__operator__noc__iexact=operator).delete()
                            # Then delete services using ORM with bulk delete to bypass cascade
                            services_to_delete = Service.objects.filter(operator__noc__iexact=operator)
                            service_ids = list(services_to_delete.values_list('id', flat=True))
                            if service_ids:
                                # Delete related records manually
                                from busstops.models import StopUsage, Route
                                StopUsage.objects.filter(service_id__in=service_ids).delete()
                                Route.objects.filter(service_id__in=service_ids).delete()
                                # Delete from service_operator table
                                from django.db import connection
                                with connection.cursor() as cursor:
                                    cursor.execute('DELETE FROM busstops_service_operator WHERE service_id = ANY(%s)', [service_ids])
                                    # Finally delete services
                                    cursor.execute('DELETE FROM busstops_service WHERE id = ANY(%s)', [service_ids])
                            self.stdout.write(self.style.SUCCESS(f"Deleted {count} services (without cascade)"))
                        else:
                            raise
                else:
                    self.stdout.write("No services found to delete")
            else:
                self.stdout.write("[DRY RUN] Would delete all services for operator")
        elif clean_slate and not operator:
            self.stdout.write(self.style.ERROR("--clean-slate requires --operator to be specified"))
            return

        # Record initial state for duplicate detection
        initial_count = self.get_existing_service_count(operator)
        self.stdout.write(f"Initial service count: {initial_count}")

        # Step 1: Sync services from Bustimes API
        if not skip_bustimes:
            self.stdout.write("\n=== Step 1: Syncing services from Bustimes API ===")
            bustimes_args = []
            if operator:
                bustimes_args.extend(["--operator", operator])
            if dry_run:
                bustimes_args.append("--dry-run")
            if force:
                bustimes_args.append("--force")
            
            try:
                call_command("sync_bustimes_services", *bustimes_args)
                self.stdout.write(self.style.SUCCESS("Bustimes services sync complete"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error syncing Bustimes services: {e}"))
        else:
            self.stdout.write("Skipping Bustimes services sync")

        # Step 2: Import TNDS data
        if not skip_tnds and tnds_username and tnds_password:
            self.stdout.write("\n=== Step 2: Importing TNDS data ===")
            try:
                call_command("import_tnds", tnds_username, tnds_password)
                self.stdout.write(self.style.SUCCESS("TNDS import complete"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error importing TNDS data: {e}"))
        elif not skip_tnds:
            self.stdout.write(self.style.WARNING("Skipping TNDS import (no credentials provided)"))
        else:
            self.stdout.write("Skipping TNDS import")

        # Step 3: Import Passenger data
        if not skip_passenger:
            self.stdout.write("\n=== Step 3: Importing Passenger data ===")
            # import_passenger expects operator_name as optional positional argument
            if operator:
                try:
                    call_command("import_passenger", operator)
                    self.stdout.write(self.style.SUCCESS("Passenger import complete"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error importing Passenger data: {e}"))
            else:
                try:
                    call_command("import_passenger")
                    self.stdout.write(self.style.SUCCESS("Passenger import complete"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error importing Passenger data: {e}"))
        else:
            self.stdout.write("Skipping Passenger import")

        # Step 4: Import BODS data
        if not skip_bods:
            self.stdout.write("\n=== Step 4: Importing BODS data ===")
            if bods_api_key:
                bods_args = [bods_api_key]
                if operator:
                    bods_args.append(operator)
                
                try:
                    call_command("import_bod_timetables", *bods_args)
                    self.stdout.write(self.style.SUCCESS("BODS import complete"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error importing BODS data: {e}"))
            else:
                self.stdout.write(self.style.WARNING("Skipping BODS import (no API key provided - set BODS_API_KEY in .env or use --bods-api-key)"))
        else:
            self.stdout.write("Skipping BODS import")

        # Final duplicate check
        final_count = self.get_existing_service_count(operator)
        self.stdout.write(f"\nFinal service count: {final_count}")
        self.stdout.write(f"Services added: {final_count - initial_count}")

        duplicates = self.check_for_duplicates(operator)
        if duplicates:
            self.stdout.write(
                self.style.WARNING(
                    f"Found {len(duplicates)} potential duplicate service codes/line names. "
                    "Individual import commands handle duplicate prevention."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("No duplicate services detected"))

        self.stdout.write("\n=== Comprehensive service sync complete ===")
        self.stdout.write("All data has been linked together with duplicate prevention handled by individual import commands.")
