"""
Silverstone Vehicle Operator Update Script

This script fetches vehicle data from bustimes.org for GP1, GP2, and GP3 services,
then updates their operators to FTS with the original NOC as a note.

Usage:
    python scripts/silverstone.py [--dry-run]
"""
import os
import sys
import re
import argparse
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError
from bs4 import BeautifulSoup
import psycopg2
from urllib.parse import urlparse
from tqdm import tqdm

# Load .env.dev file explicitly
env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env.dev')
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Get database URL from environment
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    print("ERROR: DATABASE_URL not found in environment")
    sys.exit(1)

# Parse database URL (postgis://user:pass@host:port/db)
parsed = urlparse(database_url.replace('postgis://', 'postgresql://'))

# Try to connect - first with parsed hostname, then with localhost if that fails
db_host = parsed.hostname
db_port = parsed.port or 5432

print(f"Attempting to connect to database at {db_host}:{db_port}...")

try:
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database=parsed.path[1:],  # Remove leading /
        user=parsed.username,
        password=parsed.password
    )
    print("Database connection successful!")
except psycopg2.OperationalError as e:
    print(f"Failed to connect to {db_host}:{db_port}: {e}")
    print("Trying localhost instead...")
    try:
        conn = psycopg2.connect(
            host='localhost',
            port=db_port,
            database=parsed.path[1:],
            user=parsed.username,
            password=parsed.password
        )
        print("Database connection successful via localhost!")
    except psycopg2.OperationalError as e2:
        print(f"Failed to connect to localhost:{db_port}: {e2}")
        print("Please ensure PostgreSQL is running and accessible.")
        sys.exit(1)


def get_today_date():
    """Get today's date in YYYY-MM-DD format."""
    return datetime.now().strftime('%Y-%m-%d')


def fetch_vehicles_from_bustimes(noc, service, date, verbose=False):
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
        print(f"Fetching: {url}")
    
    try:
        with urlopen(url, timeout=30) as response:
            html = response.read().decode('utf-8')
    except URLError as e:
        if verbose:
            print(f"Error fetching {url}: {e}")
        return []
    
    soup = BeautifulSoup(html, 'html.parser')
    registrations = []
    
    # Find all table rows with vehicle links
    table = soup.find('table')
    if not table:
        if verbose:
            print(f"No table found on {url}")
        return []
    
    tbody = table.find('tbody')
    if not tbody:
        if verbose:
            print(f"No tbody found on {url}")
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
                print(f"  Found vehicle: {reg}")
    
    if verbose:
        print(f"  Total vehicles found: {len(registrations)}")
    return registrations


def update_vehicle_operator(reg, new_noc, original_noc, dry_run=False, verbose=False):
    """
    Update a vehicle's operator and set the original NOC as a note using raw SQL.
    
    Args:
        reg: Vehicle registration plate
        new_noc: The new operator NOC (FTS)
        original_noc: The original operator NOC to be stored in notes
        dry_run: If True, don't actually update the database
        verbose: If True, print detailed output
    """
    # Clean registration (remove spaces)
    reg = reg.upper().replace(' ', '')
    
    cursor = conn.cursor()
    
    # Check if the FTS operator exists
    cursor.execute(
        "SELECT noc FROM busstops_operator WHERE noc = %s",
        [new_noc]
    )
    fts_operator = cursor.fetchone()
    
    if not fts_operator:
        if verbose:
            print(f"    ERROR: Operator {new_noc} not found in database")
        cursor.close()
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
            print(f"    Vehicle not found in database: {reg}")
        cursor.close()
        return False
    
    updated_count = 0
    for vehicle_id, current_operator_id, current_notes in vehicles:
        if verbose:
            print(f"    {'[DRY RUN] ' if dry_run else ''}Updating vehicle {vehicle_id}: {reg}")
            print(f"      Current operator ID: {current_operator_id}")
            print(f"      New operator: {new_noc} (ID: {fts_operator_id})")
            print(f"      Setting note to: {original_noc}")
        
        if not dry_run:
            # Update the vehicle
            cursor.execute(
                """
                UPDATE vehicles_vehicle
                SET operator_id = %s, notes = %s
                WHERE id = %s
                """,
                [fts_operator_id, original_noc, vehicle_id]
            )
            updated_count += 1
        else:
            updated_count += 1
    
    if not dry_run:
        conn.commit()
    cursor.close()
    return updated_count > 0


def get_all_nocs():
    """Fetch all NOC codes from the database."""
    cursor = conn.cursor()
    cursor.execute("SELECT noc FROM busstops_operator ORDER BY noc")
    nocs = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return nocs


def main(dry_run=False, verbose=False):
    """Main function to process GP1, GP2, and GP3 services."""
    today = get_today_date()
    new_noc = "FTS"
    
    # Services to process
    services = ["GP1", "GP2", "GP3"]
    
    # Fetch all NOCs from database
    all_nocs = get_all_nocs()
    
    print("=" * 80)
    print("SILVERSTONE VEHICLE OPERATOR UPDATE")
    print("=" * 80)
    print(f"Date: {today}")
    print(f"Target operator: {new_noc}")
    print(f"Mode: {'DRY RUN - No changes will be made' if dry_run else 'LIVE - Changes will be applied'}")
    print(f"Checking {len(all_nocs)} operators for GP services...")
    print("")
    
    total_updated = 0
    total_vehicles_found = 0
    results = []
    
    # Progress bar for NOCs
    for noc in tqdm(all_nocs, desc="Checking operators", unit="NOC"):
        noc_vehicle_count = 0
        
        for service in services:
            registrations = fetch_vehicles_from_bustimes(noc, service, today, verbose=verbose)
            
            if registrations:
                noc_vehicle_count += len(registrations)
                total_vehicles_found += len(registrations)
                
                if verbose:
                    print(f"\nProcessing {noc}:{service}")
                    print(f"  Updating {len(registrations)} vehicle(s)...")
                
                for reg in registrations:
                    if update_vehicle_operator(reg, new_noc, noc, dry_run=dry_run, verbose=verbose):
                        total_updated += 1
        
        # Store result for this NOC
        if noc_vehicle_count > 0:
            results.append((noc, noc_vehicle_count))
    
    # Print summary of results
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    
    if results:
        print(f"\nOperators with vehicles found:")
        for noc, count in sorted(results, key=lambda x: x[1], reverse=True):
            print(f"  {noc}: {count} vehicle(s)")
    else:
        print("\nNo vehicles found for any operator.")
    
    print("\n" + "=" * 80)
    print(f"TOTAL: {total_updated} vehicle(s) {'would be ' if dry_run else ''}updated")
    print(f"TOTAL: {total_vehicles_found} vehicle(s) found across all operators")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Update Silverstone GP service vehicles to FTS operator')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - do not make actual changes')
    parser.add_argument('--verbose', action='store_true', help='Verbose output - show detailed progress')
    args = parser.parse_args()
    
    try:
        main(dry_run=args.dry_run, verbose=args.verbose)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
