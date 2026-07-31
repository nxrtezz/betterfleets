"""
FHAM Service Validation Script

This script generates a report of FHAM services missing line names and descriptions.
FHAM (First Hampshire & Dorset) is the acceptance test - we need 0 missing line names
and 0 missing descriptions before proceeding to service merging.

Usage:
    python scripts/validate_fham_services.py
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'buses.settings')

# Try to setup Django without GDAL
try:
    django.setup()
except Exception as e:
    print(f"Warning: Django setup failed: {e}")
    print("This script requires Django to be properly configured with GDAL.")
    print("Please install GDAL or set GDAL_LIBRARY_PATH in settings.")
    sys.exit(1)

from django.db import connection
from django.utils import timezone


def validate_fham_services():
    """Generate report of FHAM services missing line names and descriptions."""
    
    print("=" * 80)
    print("FHAM SERVICE VALIDATION REPORT")
    print("=" * 80)
    print("")
    
    with connection.cursor() as cursor:
        # Get total services
        cursor.execute("SELECT COUNT(*) FROM busstops_service")
        total_services = cursor.fetchone()[0]
        
        # Get FHAM operator ID (First Hampshire & Dorset)
        cursor.execute(
            "SELECT noc FROM busstops_operator WHERE name ILIKE '%first%' AND name ILIKE '%hampshire%'"
        )
        fham_result = cursor.fetchone()
        
        if not fham_result:
            print("ERROR: FHAM operator not found in database")
            print("Please ensure FHAM operator exists with name containing 'first' and 'hampshire'")
            return
        
        fham_noc = fham_result[0]
        print(f"FHAM Operator NOC: {fham_noc}")
        print("")
        
        # Get total FHAM services
        cursor.execute(
            """
            SELECT COUNT(DISTINCT s.id)
            FROM busstops_service s
            INNER JOIN busstops_service_operators so ON s.id = so.service_id
            INNER JOIN busstops_operator o ON so.operator_id = o.noc
            WHERE o.noc = %s
            """,
            [fham_noc]
        )
        total_fham_services = cursor.fetchone()[0]
        
        print(f"Total FHAM services: {total_fham_services}")
        print("")
        
        # Get FHAM services missing line name
        cursor.execute(
            """
            SELECT s.id, s.service_code, s.line_name, s.description
            FROM busstops_service s
            INNER JOIN busstops_service_operators so ON s.id = so.service_id
            INNER JOIN busstops_operator o ON so.operator_id = o.noc
            WHERE o.noc = %s
            AND (s.line_name IS NULL OR s.line_name = '')
            ORDER BY s.service_code
            """,
            [fham_noc]
        )
        missing_line_names = cursor.fetchall()
        
        print(f"FHAM services missing line name: {len(missing_line_names)}")
        if missing_line_names:
            print("  Service codes:")
            for row in missing_line_names[:20]:
                print(f"    {row[1]} (ID: {row[0]})")
            if len(missing_line_names) > 20:
                print(f"    ... and {len(missing_line_names) - 20} more")
        print("")
        
        # Get FHAM services missing description
        cursor.execute(
            """
            SELECT s.id, s.service_code, s.line_name, s.description
            FROM busstops_service s
            INNER JOIN busstops_service_operators so ON s.id = so.service_id
            INNER JOIN busstops_operator o ON so.operator_id = o.noc
            WHERE o.noc = %s
            AND (s.description IS NULL OR s.description = '')
            ORDER BY s.service_code
            """,
            [fham_noc]
        )
        missing_descriptions = cursor.fetchall()
        
        print(f"FHAM services missing description: {len(missing_descriptions)}")
        if missing_descriptions:
            print("  Service codes:")
            for row in missing_descriptions[:20]:
                print(f"    {row[1]} (ID: {row[0]})")
            if len(missing_descriptions) > 20:
                print(f"    ... and {len(missing_descriptions) - 20} more")
        print("")
        
        # Get FHAM services missing both
        cursor.execute(
            """
            SELECT s.id, s.service_code, s.line_name, s.description
            FROM busstops_service s
            INNER JOIN busstops_service_operators so ON s.id = so.service_id
            INNER JOIN busstops_operator o ON so.operator_id = o.noc
            WHERE o.noc = %s
            AND (s.line_name IS NULL OR s.line_name = '')
            AND (s.description IS NULL OR s.description = '')
            ORDER BY s.service_code
            """,
            [fham_noc]
        )
        missing_both = cursor.fetchall()
        
        print(f"FHAM services missing both line name and description: {len(missing_both)}")
        if missing_both:
            print("  Service codes:")
            for row in missing_both[:20]:
                print(f"    {row[1]} (ID: {row[0]})")
            if len(missing_both) > 20:
                print(f"    ... and {len(missing_both) - 20} more")
        print("")
        
        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total services in database: {total_services}")
        print(f"Total FHAM services: {total_fham_services}")
        print(f"FHAM services missing line name: {len(missing_line_names)}")
        print(f"FHAM services missing description: {len(missing_descriptions)}")
        print(f"FHAM services missing both: {len(missing_both)}")
        print("")
        
        # Acceptance criteria
        print("ACCEPTANCE CRITERIA:")
        print(f"Missing line names = 0: {'PASS' if len(missing_line_names) == 0 else 'FAIL'}")
        print(f"Missing descriptions = 0: {'PASS' if len(missing_descriptions) == 0 else 'FAIL'}")
        print("")
        
        if len(missing_line_names) == 0 and len(missing_descriptions) == 0:
            print("STATUS: FHAM validation PASSED - Proceed to service merging")
        else:
            print("STATUS: FHAM validation FAILED - Fix missing data before proceeding to service merging")
        
        print("=" * 80)
        
        return {
            'total_services': total_services,
            'total_fham_services': total_fham_services,
            'missing_line_names': len(missing_line_names),
            'missing_descriptions': len(missing_descriptions),
            'missing_both': len(missing_both),
            'passed': len(missing_line_names) == 0 and len(missing_descriptions) == 0
        }


if __name__ == "__main__":
    try:
        result = validate_fham_services()
        sys.exit(0 if result['passed'] else 1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
