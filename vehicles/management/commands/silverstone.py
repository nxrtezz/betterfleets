"""
Silverstone Vehicle Operator Update Command

This command fetches vehicle data from bustimes.org for GP1, GP2, and GP3 services,
then updates their operators to FTS with the original NOC as a note.

Usage:
    python manage.py silverstone [--dry-run] [--verbose]
    python manage.py silverstone --reg AB12ABC [--dry-run] [--verbose]
"""
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError
from bs4 import BeautifulSoup
import re

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import IntegrityError
from tqdm import tqdm


class Command(BaseCommand):
    help = 'Update Silverstone GP service vehicles to FTS operator with original NOC as note'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Dry run - do not make actual changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Verbose output - show detailed progress',
        )
        parser.add_argument(
            '--reg',
            type=str,
            help='Manually move a specific vehicle by registration plate',
        )
        parser.add_argument(
            '--reg_file',
            type=str,
            help='Path to a text file containing registration plates (one per line)',
        )
        parser.add_argument(
            '--home-time',
            action='store_true',
            help='Transfer vehicles back to their original fleet based on their note (NOC code)',
        )

    def get_today_date(self):
        """Get today's date in YYYY-MM-DD format."""
        return datetime.now().strftime('%Y-%m-%d')

    def fetch_vehicles_from_bustimes(self, noc, service, date, verbose=False):
        """
        Fetch vehicle data from bustimes.org for a specific service.
        
        Args:
            noc: The operator NOC code (e.g., SWWD, BLUS)
            service: The service code (GP1, GP2, GP3)
            date: The date in YYYY-MM-DD format
            verbose: If True, print detailed output
        
        Returns:
            List of vehicle registration plates found on the page
        """
        url = f"https://bustimes.org/services/{noc}:{service}/vehicles?date={date}"
        if verbose:
            self.stdout.write(f"Fetching: {url}")
        
        try:
            with urlopen(url, timeout=30) as response:
                html = response.read().decode('utf-8')
        except URLError as e:
            if verbose:
                self.stdout.write(self.style.ERROR(f"Error fetching {url}: {e}"))
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        registrations = []
        
        # Find all table rows with vehicle links
        table = soup.find('table')
        if not table:
            if verbose:
                self.stdout.write(f"No table found on {url}")
            return []
        
        tbody = table.find('tbody')
        if not tbody:
            if verbose:
                self.stdout.write(f"No tbody found on {url}")
            return []
        
        for row in tbody.find_all('tr'):
            # Find the first cell with the vehicle link
            first_cell = row.find('td')
            if not first_cell:
                continue
            
            link = first_cell.find('a')
            if not link:
                continue
            
            # Extract registration from the link text
            # Format: "1819 - HF26 YRY" or similar
            text = link.get_text()
            # Extract registration plate (usually the last part with a space)
            match = re.search(r'[A-Z]{2}\d{2}\s?[A-Z]{3}', text.upper())
            if match:
                reg = match.group(0).replace(' ', '')
                registrations.append(reg)
                if verbose:
                    self.stdout.write(f"  Found vehicle: {reg}")
        
        if verbose:
            self.stdout.write(f"  Total vehicles found: {len(registrations)}")
        return registrations

    def update_vehicle_operator(self, reg, new_noc, original_noc, dry_run=False, verbose=False):
        """
        Update a vehicle's operator and set the original NOC as a note.
        
        Args:
            reg: Vehicle registration plate
            new_noc: The new operator NOC (FTS)
            original_noc: The original operator NOC to be stored in notes
            dry_run: If True, don't actually update the database
            verbose: If True, print detailed output
        """
        # Clean registration (remove spaces)
        reg = reg.upper().replace(' ', '')
        
        with connection.cursor() as cursor:
            # Check if the FTS operator exists
            cursor.execute(
                "SELECT noc FROM busstops_operator WHERE noc = %s",
                [new_noc]
            )
            fts_operator = cursor.fetchone()
            
            if not fts_operator:
                if verbose:
                    self.stdout.write(self.style.ERROR(f"    ERROR: Operator {new_noc} not found in database"))
                return False
            
            fts_operator_id = fts_operator[0]
            
            # Find vehicles by registration
            cursor.execute(
                "SELECT id, operator_id, notes FROM vehicles_vehicle WHERE reg = %s",
                [reg]
            )
            vehicles = cursor.fetchall()
            
            if not vehicles:
                if verbose:
                    self.stdout.write(f"    Vehicle not found in database: {reg}")
                return False
            
            updated_count = 0
            for vehicle_id, current_operator_id, current_notes in vehicles:
                if verbose:
                    self.stdout.write(f"    {'[DRY RUN] ' if dry_run else ''}Updating vehicle {vehicle_id}: {reg}")
                    self.stdout.write(f"      Current operator ID: {current_operator_id}")
                    self.stdout.write(f"      New operator: {new_noc} (ID: {fts_operator_id})")
                    self.stdout.write(f"      Setting note to: {original_noc}")
                
                if not dry_run:
                    # Update the vehicle
                    try:
                        cursor.execute(
                            """
                            UPDATE vehicles_vehicle
                            SET operator_id = %s, notes = %s
                            WHERE id = %s
                            """,
                            [fts_operator_id, original_noc, vehicle_id]
                        )
                        updated_count += 1
                    except IntegrityError as e:
                        if verbose:
                            self.stdout.write(self.style.ERROR(f"    ERROR: IntegrityError for vehicle {vehicle_id}: {e}"))
                        # Continue to next vehicle instead of failing completely
                else:
                    updated_count += 1
            
            return updated_count > 0

    def parse_reg_file(self, file_path):
        """
        Parse registration plates from a text file.
        
        Args:
            file_path: Path to the text file containing registration plates (one per line)
        
        Returns:
            List of registration plates (cleaned and uppercase)
        """
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            registrations = []
            for line in lines:
                reg = line.strip()
                if reg:  # Skip empty lines
                    # Clean registration (remove spaces and convert to uppercase)
                    reg = reg.upper().replace(' ', '')
                    registrations.append(reg)
            
            return registrations
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f"ERROR: File not found: {file_path}"))
            return []
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"ERROR: Failed to read file {file_path}: {e}"))
            return []

    def get_all_nocs(self):
        """Fetch all NOC codes from the database."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT noc FROM busstops_operator ORDER BY noc")
            nocs = [row[0] for row in cursor.fetchall()]
        return nocs

    def transfer_vehicle_home(self, reg, dry_run=False, verbose=False):
        """
        Transfer a vehicle back to its original fleet based on its note (NOC code).
        
        Args:
            reg: Vehicle registration plate
            dry_run: If True, don't actually update the database
            verbose: If True, print detailed output
        
        Returns:
            True if successful, False otherwise
        """
        # Clean registration (remove spaces)
        reg = reg.upper().replace(' ', '')
        
        with connection.cursor() as cursor:
            # Find vehicles by registration and get their note
            cursor.execute(
                "SELECT id, operator_id, notes FROM vehicles_vehicle WHERE reg = %s",
                [reg]
            )
            vehicles = cursor.fetchall()
            
            if not vehicles:
                if verbose:
                    self.stdout.write(f"    Vehicle not found in database: {reg}")
                return False
            
            updated_count = 0
            for vehicle_id, current_operator_id, note in vehicles:
                # Clean the note - strip whitespace and convert to uppercase
                if note:
                    note = note.strip().upper()
                
                # Check if note exists and is a valid NOC (3-5 chars)
                if not note or len(note) < 3 or len(note) > 5:
                    if verbose:
                        self.stdout.write(self.style.ERROR(f"    Vehicle {vehicle_id}: {reg} has no valid note (found: '{note}', expected 3-5 char NOC)"))
                    continue
                
                # Check if the NOC exists in the database
                cursor.execute(
                    "SELECT noc FROM busstops_operator WHERE noc = %s",
                    [note]
                )
                target_operator = cursor.fetchone()
                
                if not target_operator:
                    if verbose:
                        self.stdout.write(self.style.ERROR(f"    ERROR: Operator {note} not found in database for vehicle {reg}"))
                    continue
                
                target_noc = target_operator[0]
                
                # Skip if vehicle is already in the target fleet
                if current_operator_id == target_noc:
                    if verbose:
                        self.stdout.write(self.style.WARNING(f"    Vehicle {reg} is already in {target_noc} fleet, skipping"))
                    continue
                
                if verbose:
                    self.stdout.write(f"    {'[DRY RUN] ' if dry_run else ''}Transferring vehicle {vehicle_id}: {reg}")
                    self.stdout.write(f"      Current operator: {current_operator_id}")
                    self.stdout.write(f"      Target operator: {target_noc} (from note: {note})")
                
                if not dry_run:
                    try:
                        cursor.execute(
                            """
                            UPDATE vehicles_vehicle
                            SET operator_id = %s, notes = ''
                            WHERE id = %s
                            """,
                            [target_noc, vehicle_id]
                        )
                        updated_count += 1
                    except IntegrityError as e:
                        if verbose:
                            self.stdout.write(self.style.ERROR(f"    ERROR: IntegrityError for vehicle {vehicle_id}: {e}"))
                else:
                    updated_count += 1
            
            return updated_count > 0

    def handle(self, *args, **options):
        """Main function to process GP1, GP2, and GP3 services."""
        dry_run = options.get('dry_run', False)
        verbose = options.get('verbose', False)
        manual_reg = options.get('reg')
        reg_file = options.get('reg_file')
        home_time = options.get('home_time', False)
        
        today = self.get_today_date()
        new_noc = "FTS"
        
        # Home-time mode: transfer vehicles back to their original fleets
        if home_time:
            self.stdout.write("=" * 80)
            self.stdout.write("HOME-TIME VEHICLE TRANSFER")
            self.stdout.write("=" * 80)
            self.stdout.write(f"Mode: {'DRY RUN - No changes will be made' if dry_run else 'LIVE - Changes will be applied'}")
            self.stdout.write("")
            
            updated_count = 0
            failed_count = 0
            
            # If manual reg or reg_file is specified, process only those vehicles
            if manual_reg:
                registrations = [manual_reg.upper().replace(' ', '')]
            elif reg_file:
                registrations = self.parse_reg_file(reg_file)
                if not registrations:
                    self.stdout.write(self.style.ERROR("ERROR: No registrations found in file or file could not be read"))
                    return
            else:
                # Process all vehicles in FTS fleet that have a note
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT reg FROM vehicles_vehicle WHERE operator_id = %s AND notes IS NOT NULL",
                        [new_noc]
                    )
                    registrations = [row[0] for row in cursor.fetchall()]
                
                if not registrations:
                    self.stdout.write("No vehicles found in FTS fleet with notes")
                    return
            
            self.stdout.write(f"Registrations to process: {len(registrations)}")
            self.stdout.write("")
            
            for reg in registrations:
                if self.transfer_vehicle_home(reg, dry_run=dry_run, verbose=verbose):
                    if verbose:
                        self.stdout.write(self.style.SUCCESS(f"  Successfully {'would transfer' if dry_run else 'transferred'} vehicle {reg}"))
                    updated_count += 1
                else:
                    self.stdout.write(self.style.ERROR(f"  Failed to transfer vehicle {reg}"))
                    failed_count += 1
            
            self.stdout.write("")
            self.stdout.write("=" * 80)
            self.stdout.write("HOME-TIME TRANSFER SUMMARY")
            self.stdout.write("=" * 80)
            self.stdout.write(f"Total registrations processed: {len(registrations)}")
            self.stdout.write(self.style.SUCCESS(f"Successfully {'would transfer' if dry_run else 'transferred'}: {updated_count}"))
            self.stdout.write(self.style.ERROR(f"Failed: {failed_count}"))
            self.stdout.write("=" * 80)
            return
        
        # File mode: process multiple registrations from a file
        if reg_file:
            registrations = self.parse_reg_file(reg_file)
            
            if not registrations:
                self.stdout.write(self.style.ERROR("ERROR: No registrations found in file or file could not be read"))
                return
            
            self.stdout.write("=" * 80)
            self.stdout.write("BATCH VEHICLE OPERATOR UPDATE FROM FILE")
            self.stdout.write("=" * 80)
            self.stdout.write(f"File: {reg_file}")
            self.stdout.write(f"Registrations to process: {len(registrations)}")
            self.stdout.write(f"Target operator: {new_noc}")
            self.stdout.write(f"Mode: {'DRY RUN - No changes will be made' if dry_run else 'LIVE - Changes will be applied'}")
            self.stdout.write("")
            
            updated_count = 0
            failed_count = 0
            
            for reg in registrations:
                # Get current operator NOC and status for the vehicle
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT o.noc, v.withdrawn, v.preserved
                        FROM vehicles_vehicle v
                        JOIN busstops_operator o ON v.operator_id = o.noc
                        WHERE v.reg = %s
                        LIMIT 1
                        """,
                        [reg]
                    )
                    result = cursor.fetchone()
                
                if not result:
                    self.stdout.write(self.style.ERROR(f"  Vehicle not found in database: {reg}"))
                    failed_count += 1
                    continue
                
                from_noc, withdrawn, preserved = result
                
                # Strict check: only move non-withdrawn and non-preserved vehicles
                if withdrawn:
                    self.stdout.write(self.style.ERROR(f"  Vehicle {reg} is withdrawn and cannot be moved"))
                    failed_count += 1
                    continue
                
                if preserved:
                    self.stdout.write(self.style.ERROR(f"  Vehicle {reg} is preserved and cannot be moved"))
                    failed_count += 1
                    continue
                
                # Skip if vehicle is already in FTS fleet
                if from_noc == new_noc:
                    self.stdout.write(self.style.WARNING(f"  Vehicle {reg} is already in FTS fleet, skipping"))
                    failed_count += 1
                    continue
                
                if verbose:
                    self.stdout.write(f"  Processing {reg} (from {from_noc})")
                
                if self.update_vehicle_operator(reg, new_noc, from_noc, dry_run=dry_run, verbose=verbose):
                    if verbose:
                        self.stdout.write(self.style.SUCCESS(f"  Successfully {'would update' if dry_run else 'updated'} vehicle {reg}"))
                    updated_count += 1
                else:
                    self.stdout.write(self.style.ERROR(f"  Failed to update vehicle {reg}"))
                    failed_count += 1
            
            self.stdout.write("")
            self.stdout.write("=" * 80)
            self.stdout.write("BATCH UPDATE SUMMARY")
            self.stdout.write("=" * 80)
            self.stdout.write(f"Total registrations processed: {len(registrations)}")
            self.stdout.write(self.style.SUCCESS(f"Successfully {'would update' if dry_run else 'updated'}: {updated_count}"))
            self.stdout.write(self.style.ERROR(f"Failed: {failed_count}"))
            self.stdout.write("=" * 80)
            return
        
        # Manual mode: move a specific vehicle
        if manual_reg:
            # Get current operator NOC and status for the vehicle
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT o.noc, v.withdrawn, v.preserved
                    FROM vehicles_vehicle v
                    JOIN busstops_operator o ON v.operator_id = o.noc
                    WHERE v.reg = %s
                    LIMIT 1
                    """,
                    [manual_reg.upper().replace(' ', '')]
                )
                result = cursor.fetchone()
            
            if not result:
                self.stdout.write(self.style.ERROR(f"ERROR: Vehicle {manual_reg} not found in database"))
                return
            
            from_noc, withdrawn, preserved = result
            
            # Strict check: only move non-withdrawn and non-preserved vehicles
            if withdrawn:
                self.stdout.write(self.style.ERROR(f"ERROR: Vehicle {manual_reg} is withdrawn and cannot be moved"))
                return
            
            if preserved:
                self.stdout.write(self.style.ERROR(f"ERROR: Vehicle {manual_reg} is preserved and cannot be moved"))
                return
            
            # Skip if vehicle is already in FTS fleet
            if from_noc == new_noc:
                self.stdout.write(self.style.WARNING(f"Vehicle {manual_reg} is already in FTS fleet, skipping"))
                return
            
            self.stdout.write("=" * 80)
            self.stdout.write("MANUAL VEHICLE OPERATOR UPDATE")
            self.stdout.write("=" * 80)
            self.stdout.write(f"Vehicle: {manual_reg}")
            self.stdout.write(f"Target operator: {new_noc}")
            self.stdout.write(f"Original NOC (note): {from_noc}")
            self.stdout.write(f"Mode: {'DRY RUN - No changes will be made' if dry_run else 'LIVE - Changes will be applied'}")
            self.stdout.write("")
            
            if self.update_vehicle_operator(manual_reg, new_noc, from_noc, dry_run=dry_run, verbose=True):
                self.stdout.write(self.style.SUCCESS(f"Successfully {'would update' if dry_run else 'updated'} vehicle {manual_reg}"))
            else:
                self.stdout.write(self.style.ERROR(f"Failed to update vehicle {manual_reg}"))
            return
        
        # Automatic mode: scan all operators for GP services
        services = ["GP1", "GP2", "GP3"]
        
        # Fetch all NOCs from database
        all_nocs = self.get_all_nocs()
        
        self.stdout.write("=" * 80)
        self.stdout.write("SILVERSTONE VEHICLE OPERATOR UPDATE")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Date: {today}")
        self.stdout.write(f"Target operator: {new_noc}")
        self.stdout.write(f"Mode: {'DRY RUN - No changes will be made' if dry_run else 'LIVE - Changes will be applied'}")
        self.stdout.write(f"Checking {len(all_nocs)} operators for GP services...")
        self.stdout.write("")
        
        total_updated = 0
        total_vehicles_found = 0
        results = []
        
        # Progress bar for NOCs
        for noc in tqdm(all_nocs, desc="Checking operators", unit="NOC"):
            noc_vehicle_count = 0
            
            for service in services:
                registrations = self.fetch_vehicles_from_bustimes(noc, service, today, verbose=verbose)
                
                if registrations:
                    noc_vehicle_count += len(registrations)
                    total_vehicles_found += len(registrations)
                    
                    if verbose:
                        self.stdout.write(f"\nProcessing {noc}:{service}")
                        self.stdout.write(f"  Updating {len(registrations)} vehicle(s)...")
                    
                    for reg in registrations:
                        if self.update_vehicle_operator(reg, new_noc, noc, dry_run=dry_run, verbose=verbose):
                            total_updated += 1
            
            # Store result for this NOC
            if noc_vehicle_count > 0:
                results.append((noc, noc_vehicle_count))
        
        # Print summary of results
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("RESULTS SUMMARY")
        self.stdout.write("=" * 80)
        
        if results:
            self.stdout.write(f"\nOperators with vehicles found:")
            for noc, count in sorted(results, key=lambda x: x[1], reverse=True):
                self.stdout.write(f"  {noc}: {count} vehicle(s)")
        else:
            self.stdout.write("\nNo vehicles found for any operator.")
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(f"TOTAL: {total_updated} vehicle(s) {'would be ' if dry_run else ''}updated")
        self.stdout.write(f"TOTAL: {total_vehicles_found} vehicle(s) found across all operators")
        self.stdout.write("=" * 80)
