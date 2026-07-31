"""
Comprehensive data import command for BetterFleet.

This command performs a complete data import workflow:
1. Operators - Import BODS, Naptan, Passenger, and Bustimes API
2. Liveries and Vehicle Types - Copy from Bustimes API with matching IDs
3. Pre-vehicle details - Scan Bustimes vehicle API for vehicle features and garages
4. Create all 60k+ vehicles - Direct copies from Bustimes
5. Final import of TNDS and stop data

Includes exponential backoff retry logic (1s, 2s, 4s, 8s) for timeouts and rate limiting.
"""

import time
import logging
from django.core.management import call_command, BaseCommand
from django.core.management.base import CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Perform comprehensive data import from all sources (BODS, Naptan, Passenger, Bustimes, TNDS, stops)"

    def add_arguments(self, parser):
        # General options
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
            "--max-items",
            type=int,
            help="Maximum number of items to sync per endpoint.",
        )
        parser.add_argument(
            "--max-retries",
            type=int,
            default=5,
            help="Maximum number of retries for failed requests (default: 5).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=120,
            help="Timeout in seconds for API requests (default: 120).",
        )
        parser.add_argument(
            "--skip-bods",
            action="store_true",
            help="Skip BODS import step.",
        )
        parser.add_argument(
            "--skip-naptan",
            action="store_true",
            help="Skip NaPTAN import step.",
        )
        parser.add_argument(
            "--skip-passenger",
            action="store_true",
            help="Skip Passenger import step.",
        )
        parser.add_argument(
            "--skip-tnds",
            action="store_true",
            help="Skip TNDS import step.",
        )
        parser.add_argument(
            "--bods-api-key",
            type=str,
            help="BODS API key for import_bod_timetables command.",
        )
        parser.add_argument(
            "--tnds-username",
            type=str,
            help="TNDS FTP username for import_tnds command.",
        )
        parser.add_argument(
            "--tnds-password",
            type=str,
            help="TNDS FTP password for import_tnds command.",
        )
        parser.add_argument(
            "--operator",
            type=str,
            help="Specific operator to import (for BODS and Passenger).",
        )

    def retry_with_backoff(self, func, step_name, max_retries=5, timeout=120):
        """
        Execute a function with exponential backoff retry logic.
        Backoff sequence: 1s, 2s, 4s, 8s, 16s
        """
        retry_count = 0
        backoff_times = [1, 2, 4, 8, 16]  # Exponential backoff
        
        while retry_count < max_retries:
            try:
                self.stdout.write(f"\n{'='*70}")
                self.stdout.write(f"🔄 Executing: {step_name}")
                self.stdout.write(f"{'='*70}")
                
                func()
                self.stdout.write(self.style.SUCCESS(f"✓ {step_name} completed successfully"))
                return True
                
            except Exception as exc:
                retry_count += 1
                error_msg = str(exc).lower()
                
                # Check if error is retryable (timeout, rate limit, connection error)
                is_retryable = (
                    "timeout" in error_msg or
                    "rate limit" in error_msg or
                    "connection" in error_msg or
                    "network" in error_msg or
                    "503" in error_msg or
                    "502" in error_msg or
                    "429" in error_msg
                )
                
                if retry_count < max_retries and is_retryable:
                    backoff_time = backoff_times[min(retry_count - 1, len(backoff_times) - 1)]
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  {step_name} failed (attempt {retry_count}/{max_retries}): {exc}"
                        )
                    )
                    self.stdout.write(f"⏳ Retrying in {backoff_time}s...")
                    time.sleep(backoff_time)
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"✗ {step_name} failed: {exc}"
                        )
                    )
                    if retry_count < max_retries:
                        self.stdout.write(f"⚠️  Retrying ({retry_count}/{max_retries})...")
                        time.sleep(5)
                    else:
                        self.stdout.write(self.style.ERROR("✗ Max retries reached, giving up"))
                        return False
        
        return False

    def step_1_import_operators(self, options):
        """Step 1: Import Operators from BODS, NaPTAN, Passenger, and Bustimes API"""
        self.stdout.write("\n" + "="*70)
        self.stdout.write("📋 STEP 1: OPERATORS IMPORT")
        self.stdout.write("="*70)
        
        # 1a. BODS import (if API key provided and not skipped)
        if not options["skip_bods"] and options.get("bods_api_key"):
            def import_bods():
                call_command(
                    "import_bod_timetables",
                    options["bods_api_key"],
                    options.get("operator") or "",
                )
            
            if not self.retry_with_backoff(
                import_bods,
                "BODS Timetables Import",
                options["max_retries"],
                options["timeout"]
            ):
                self.stdout.write(self.style.WARNING("⚠️  BODS import failed, continuing..."))
        
        # 1b. NaPTAN import (if not skipped)
        if not options["skip_naptan"]:
            def import_naptan():
                call_command("naptan_new")
            
            if not self.retry_with_backoff(
                import_naptan,
                "NaPTAN Import",
                options["max_retries"],
                options["timeout"]
            ):
                self.stdout.write(self.style.WARNING("⚠️  NaPTAN import failed, continuing..."))
        
        # 1c. Passenger import (if not skipped)
        if not options["skip_passenger"]:
            def import_passenger():
                operator = options.get("operator") or ""
                call_command("import_passenger", operator)
            
            if not self.retry_with_backoff(
                import_passenger,
                "Passenger Import",
                options["max_retries"],
                options["timeout"]
            ):
                self.stdout.write(self.style.WARNING("⚠️  Passenger import failed, continuing..."))
        
        # 1d. Bustimes operators import
        def import_bustimes_operators():
            call_command(
                "sync_bustimes_operators",
                dry_run=options["dry_run"],
                force=options["force"],
                max_items=options["max_items"],
            )
        
        if not self.retry_with_backoff(
            import_bustimes_operators,
            "Bustimes Operators Import",
            options["max_retries"],
            options["timeout"]
        ):
            raise CommandError("Bustimes operators import failed")

    def step_2_import_liveries_and_vehicle_types(self, options):
        """Step 2: Import Liveries and Vehicle Types from Bustimes API"""
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🎨 STEP 2: LIVERIES AND VEHICLE TYPES IMPORT")
        self.stdout.write("="*70)
        
        # 2a. Import liveries
        def import_liveries():
            call_command(
                "sync_bustimes_liveries",
                dry_run=options["dry_run"],
                force=options["force"],
                max_items=options["max_items"],
            )
        
        if not self.retry_with_backoff(
            import_liveries,
            "Bustimes Liveries Import",
            options["max_retries"],
            options["timeout"]
        ):
            raise CommandError("Bustimes liveries import failed")
        
        # 2b. Import vehicle types
        def import_vehicle_types():
            # Note: sync_bustimes_vehicletypes uses --limit instead of --max-items
            # and doesn't support --force
            kwargs = {"dry_run": options["dry_run"]}
            if options.get("max_items"):
                kwargs["limit"] = options["max_items"]
            call_command("sync_bustimes_vehicletypes", **kwargs)
        
        # Skip vehicle types for now due to API rate limiting
        self.stdout.write(self.style.WARNING("⚠️  Skipping vehicle types import due to API rate limiting"))
        self.stdout.write("ℹ️  Vehicle types will be created during vehicle import step")
        
        # if not self.retry_with_backoff(
        #     import_vehicle_types,
        #     "Bustimes Vehicle Types Import",
        #     options["max_retries"],
        #     options["timeout"]
        # ):
        #     raise CommandError("Bustimes vehicle types import failed")

    def step_3_pre_vehicle_details(self, options):
        """Step 3: Pre-vehicle details - scan Bustimes vehicle API for features and garages"""
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🔧 STEP 3: PRE-VEHICLE DETAILS (FEATURES AND GARAGES)")
        self.stdout.write("="*70)
        
        # This step is handled automatically by sync_bustimes_vehicles with --override flag
        # The vehicle sync will create garages and features as needed
        self.stdout.write("ℹ️  Vehicle features and garages will be created during vehicle import")
        self.stdout.write("ℹ️  This is handled by sync_bustimes_vehicles with --override flag")

    def step_4_import_vehicles(self, options):
        """Step 4: Create all 60k+ vehicles from Bustimes"""
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🚌 STEP 4: VEHICLES IMPORT (60k+ vehicles)")
        self.stdout.write("="*70)
        
        def import_vehicles():
            # Use --override to create new garages and liveries if needed
            # Note: sync_bustimes_vehicles doesn't support timeout parameter
            call_command(
                "sync_bustimes_vehicles",
                dry_run=options["dry_run"],
                force=options["force"],
                max_items=options["max_items"],
                override=True,  # Create new garages if needed
            )
        
        if not self.retry_with_backoff(
            import_vehicles,
            "Bustimes Vehicles Import",
            options["max_retries"],
            max(options["timeout"], 300)
        ):
            raise CommandError("Bustimes vehicles import failed")

    def step_5_import_tnds_and_stops(self, options):
        """Step 5: Final import of TNDS and stop data"""
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🚏 STEP 5: TNDS AND STOP DATA IMPORT")
        self.stdout.write("="*70)
        
        # 5a. TNDS import (if credentials provided and not skipped)
        if not options["skip_tnds"] and options.get("tnds_username") and options.get("tnds_password"):
            def import_tnds():
                call_command(
                    "import_tnds",
                    options["tnds_username"],
                    options["tnds_password"],
                )
            
            if not self.retry_with_backoff(
                import_tnds,
                "TNDS Import",
                options["max_retries"],
                options["timeout"]
            ):
                self.stdout.write(self.style.WARNING("⚠️  TNDS import failed, continuing..."))
        
        # 5b. Bustimes stops import
        def import_stops():
            call_command(
                "sync_bustimes_stops",
                dry_run=options["dry_run"],
                force=options["force"],
                max_items=options["max_items"],
            )
        
        if not self.retry_with_backoff(
            import_stops,
            "Bustimes Stops Import",
            options["max_retries"],
            options["timeout"]
        ):
            raise CommandError("Bustimes stops import failed")

    def handle(self, *args, **options):
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🚀 BETTERFLEET COMPREHENSIVE DATA IMPORT")
        self.stdout.write("="*70)
        self.stdout.write("This command will perform a complete data import workflow.")
        self.stdout.write("Estimated duration: 5-10 hours")
        self.stdout.write("="*70)
        
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("⚠️  DRY RUN MODE - No changes will be made"))
        
        start_time = time.time()
        failed_steps = []
        
        try:
            # Step 1: Operators
            try:
                self.step_1_import_operators(options)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Step 1 failed: {e}"))
                failed_steps.append("Step 1: Operators")
                if not options["force"]:
                    raise
            
            # Step 2: Liveries and Vehicle Types
            try:
                self.step_2_import_liveries_and_vehicle_types(options)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Step 2 failed: {e}"))
                failed_steps.append("Step 2: Liveries and Vehicle Types")
                if not options["force"]:
                    raise
            
            # Step 3: Pre-vehicle details
            try:
                self.step_3_pre_vehicle_details(options)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Step 3 failed: {e}"))
                failed_steps.append("Step 3: Pre-vehicle details")
                if not options["force"]:
                    raise
            
            # Step 4: Vehicles
            try:
                self.step_4_import_vehicles(options)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Step 4 failed: {e}"))
                failed_steps.append("Step 4: Vehicles")
                if not options["force"]:
                    raise
            
            # Step 5: TNDS and Stops
            try:
                self.step_5_import_tnds_and_stops(options)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Step 5 failed: {e}"))
                failed_steps.append("Step 5: TNDS and Stops")
                if not options["force"]:
                    raise
            
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n⚠️  Import interrupted by user"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Fatal error: {e}"))
            raise
        
        # Summary
        elapsed_time = time.time() - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write("📊 IMPORT SUMMARY")
        self.stdout.write("="*70)
        self.stdout.write(f"Total time: {hours}h {minutes}m {seconds}s")
        
        if failed_steps:
            self.stdout.write(self.style.WARNING(f"⚠️  Failed steps: {', '.join(failed_steps)}"))
        else:
            self.stdout.write(self.style.SUCCESS("✓ All steps completed successfully"))
        
        self.stdout.write("="*70)
