"""Import UK railway stations as stop points with CRS codes"""

import logging
import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.gis.geos import Point
from busstops.models import StopPoint, AdminArea, Region, Locality

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import UK railway stations as stop points with CRS codes from Transport Statistics API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='Path to a JSON or CSV file containing station data (alternative to API)'
        )
        parser.add_argument(
            '--url',
            type=str,
            help='URL to fetch station data from (alternative to Transport Statistics API)'
        )
        parser.add_argument(
            '--update',
            action='store_true',
            help='Update existing stations instead of skipping them'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without making changes'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of stations to import (for testing)'
        )
        parser.add_argument(
            '--crs',
            type=str,
            help='Import specific station by CRS code'
        )

    def handle(self, *args, **options):
        import json

        dry_run = options.get('dry_run', False)
        update = options.get('update', False)
        file_path = options.get('file')
        url = options.get('url')
        limit = options.get('limit')
        crs_filter = options.get('crs')

        stations = []

        # Fetch station data
        if file_path:
            self.stdout.write(f'Reading stations from {file_path}')
            if file_path.endswith('.json'):
                with open(file_path, 'r') as f:
                    stations = json.load(f)
            elif file_path.endswith('.csv'):
                import csv
                with open(file_path, 'r') as f:
                    reader = csv.DictReader(f)
                    stations = list(reader)
            else:
                self.stdout.write(self.style.ERROR('Unsupported file format. Use JSON or CSV.'))
                return
        elif url:
            self.stdout.write(f'Fetching stations from {url}')
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                stations = response.json()
            except requests.RequestException as e:
                self.stdout.write(self.style.ERROR(f'Failed to fetch stations: {e}'))
                return
        else:
            # Use Transport Statistics API by default
            self.stdout.write('Fetching stations from Transport Statistics API')
            stations = self.fetch_from_transport_statistics(limit=limit, crs=crs_filter)

        if not stations:
            self.stdout.write(self.style.WARNING('No stations to import'))
            return

        self.stdout.write(f'Found {len(stations)} stations to process')

        # Get or create default admin area and region for railway stations
        region, _ = Region.objects.get_or_create(
            id='GB',
            defaults={'name': 'Great Britain'}
        )
        admin_area, _ = AdminArea.objects.get_or_create(
            id=999,
            defaults={
                'atco_code': '999',
                'name': 'National Rail',
                'region': region
            }
        )

        imported = 0
        updated = 0
        skipped = 0
        errors = 0

        with transaction.atomic():
            for station_data in stations:
                try:
                    # Normalize station data
                    station = self.normalize_station_data(station_data)
                    if not station or not station.get('crs_code'):
                        skipped += 1
                        continue

                    crs_code = station['crs_code'].upper()
                    
                    # Use ATCO code from API if available, otherwise generate from CRS
                    atco_code = station.get('atco_code') or f'9{crs_code}'

                    # Check if station already exists
                    existing = StopPoint.objects.filter(crs_code=crs_code).first()

                    if existing:
                        if update:
                            if dry_run:
                                self.stdout.write(f'Would update: {station["name"]} ({crs_code})')
                                updated += 1
                            else:
                                self.update_station(existing, station, admin_area)
                                updated += 1
                        else:
                            skipped += 1
                        continue

                    # Create new station
                    if dry_run:
                        self.stdout.write(f'Would create: {station["name"]} ({crs_code})')
                        imported += 1
                    else:
                        self.create_station(station, admin_area, atco_code)
                        imported += 1

                except Exception as e:
                    errors += 1
                    logger.error(f'Error processing station {station_data}: {e}')
                    self.stdout.write(self.style.ERROR(f'Error: {e}'))

        self.stdout.write(self.style.SUCCESS(
            f'Import complete: {imported} imported, {updated} updated, {skipped} skipped, {errors} errors'
        ))

    def fetch_from_transport_statistics(self, limit=None, crs=None):
        """Fetch railway stations from Transport Statistics API"""
        base_url = "https://transportstatistics.com/api/stops/"
        params = {
            'active': 'true',
            'crs': '',
            'atco_code': '',
            'naptan_code': '',
            'tiploc': ''
        }
        
        if crs:
            params['crs'] = crs
        
        stations = []
        offset = 0
        page_size = 100
        
        while True:
            params['offset'] = offset
            params['limit'] = page_size
            
            try:
                response = requests.get(base_url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                results = data.get('results', [])
                if not results:
                    break
                
                # Filter for railway stations (stop_type code RLS for Rail Stations)
                rail_stations = [
                    s for s in results 
                    if s.get('stop_type', {}).get('code') == 'RLS' and s.get('crs')
                ]
                
                stations.extend(rail_stations)
                self.stdout.write(f'Fetched {len(rail_stations)} rail stations (total: {len(stations)})')
                
                # Break if no railway stations found in this page (end of rail stations)
                if not rail_stations:
                    break
                
                # Check if we've reached the limit
                if limit and len(stations) >= limit:
                    stations = stations[:limit]
                    break
                
                # Check if there are more pages
                if not data.get('next'):
                    break
                
                offset += page_size
                
            except requests.RequestException as e:
                self.stdout.write(self.style.ERROR(f'Failed to fetch from Transport Statistics API: {e}'))
                break
        
        return stations

    def normalize_station_data(self, data):
        """Normalize station data from various sources to a standard format"""
        # Handle different field names from different sources
        station = {}

        # Try common field names
        station['name'] = (
            data.get('name') or
            data.get('stationName') or
            data.get('station_name') or
            data.get('common_name')
        )

        station['crs_code'] = (
            data.get('crs') or
            data.get('crsCode') or
            data.get('crs_code') or
            data.get('code')
        )
        
        station['atco_code'] = data.get('atco_code')

        # Coordinates
        lat = data.get('lat') or data.get('latitude')
        lon = data.get('lon') or data.get('longitude') or data.get('long')

        if lat and lon:
            try:
                station['latitude'] = float(lat)
                station['longitude'] = float(lon)
            except (ValueError, TypeError):
                pass

        return station

    def create_station(self, station_data, admin_area, atco_code):
        """Create a new railway station stop point"""
        latlong = None
        if 'latitude' in station_data and 'longitude' in station_data:
            latlong = Point(
                station_data['longitude'],
                station_data['latitude']
            )

        StopPoint.objects.create(
            atco_code=atco_code,
            common_name=station_data['name'],
            crs_code=station_data['crs_code'].upper(),
            latlong=latlong,
            stop_type='RSE',  # Rail station entrance
            admin_area=admin_area,
            active=True
        )

    def update_station(self, existing, station_data, admin_area):
        """Update an existing railway station"""
        existing.common_name = station_data['name']
        existing.crs_code = station_data['crs_code'].upper()
        
        if 'latitude' in station_data and 'longitude' in station_data:
            existing.latlong = Point(
                station_data['longitude'],
                station_data['latitude']
            )
        
        existing.save(update_fields=['common_name', 'crs_code', 'latlong'])
