"""
FHAM Service Validation Script (Direct Database Connection)

This script generates a report of FHAM services missing line names and descriptions
using direct database connection to bypass GDAL dependency.

Usage:
    python scripts/validate_fham_services_direct.py
"""
import os
import sys
import psycopg2
from psycopg2.extras import DictCursor


def get_db_connection():
    """Get direct database connection from Django settings."""
    # Use Docker container database configuration
    db_config = {
        'dbname': 'postgres',
        'user': 'postgres',
        'password': 'postgres',
        'host': 'postgres',
        'port': '5432'
    }
    
    try:
        conn = psycopg2.connect(
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password'],
            host=db_config['host'],
            port=db_config['port'],
            cursor_factory=DictCursor
        )
        return conn
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        print(f"Database config: dbname={db_config['dbname']}, user={db_config['user']}, host={db_config['host']}")
        print("Please ensure PostgreSQL is running and credentials are correct.")
        return None


def validate_fham_services():
    """Generate report of FHAM services missing line names and descriptions."""
    
    conn = get_db_connection()
    if not conn:
        return None
    
    print("=" * 80)
    print("FHAM SERVICE VALIDATION REPORT")
    print("=" * 80)
    print("")
    
    try:
        with conn.cursor() as cursor:
            # Get total services
            cursor.execute("SELECT COUNT(*) FROM busstops_service")
            total_services = cursor.fetchone()['count']
            
            # Get FHAM operator ID (First Hampshire & Dorset)
            cursor.execute(
                "SELECT noc FROM busstops_operator WHERE name ILIKE '%first%' AND name ILIKE '%hampshire%'"
            )
            fham_result = cursor.fetchone()
            
            if not fham_result:
                print("ERROR: FHAM operator not found in database")
                print("Please ensure FHAM operator exists with name containing 'first' and 'hampshire'")
                return None
            
            fham_noc = fham_result['noc']
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
            total_fham_services = cursor.fetchone()['count']
            
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
                    print(f"    {row['service_code']} (ID: {row['id']})")
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
                    print(f"    {row['service_code']} (ID: {row['id']})")
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
                    print(f"    {row['service_code']} (ID: {row['id']})")
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
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        result = validate_fham_services()
        if result is None:
            sys.exit(1)
        sys.exit(0 if result['passed'] else 1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
