"""
TransitTracker scraper for importing ridden logs from user fleet completion pages.

This module fetches fleet completion pages from TransitTracker and extracts
registration numbers to create FleetRideLog entries in the database.
"""

import base64
import json
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from busstops.models import Operator
from vehicles.models import Vehicle

from .models import FleetRideLog

User = get_user_model()


@dataclass
class ScrapedVehicle:
    """Represents a vehicle found on a TransitTracker fleet completion page."""
    registration: str
    fleet_number: Optional[str] = None
    operator_noc: Optional[str] = None


class TransitTrackerScraper:
    """
    Scraper for TransitTracker fleet completion pages.
    
    Fetches pages like: https://transittracker.net/{username}/fleet-completion/BUSTIM/{operator_noc}
    and extracts registration numbers to create ridden logs.
    """
    
    BASE_URL = "https://transittracker.net"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    
    def __init__(self, username: str, datasource: str = "BUSTIM"):
        """
        Initialize the scraper.
        
        Args:
            username: TransitTracker username
            datasource: Data source (default: BUSTIM for bus operators)
        """
        self.username = username
        self.datasource = datasource
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})
    
    def check_user_exists(self) -> dict[str, any]:
        """
        Check if a TransitTracker user exists and has public statistics.
        
        Returns:
            Dictionary with 'exists' (bool), 'public' (bool), and 'error' (str if any)
        """
        url = f"{self.BASE_URL}/{self.username}/statistics"
        
        try:
            response = self.session.get(url, timeout=30)
            
            if response.status_code == 404:
                return {"exists": False, "public": False, "error": "User not found"}
            
            if response.status_code == 403:
                return {"exists": True, "public": False, "error": "Profile is not public"}
            
            response.raise_for_status()
            return {"exists": True, "public": True, "error": None}
            
        except requests.RequestException as e:
            return {"exists": False, "public": False, "error": str(e)}
    
    def get_operators_from_main_page(self) -> list[str]:
        """
        Get list of operators the user has logged from the main fleet completion page.
        
        Returns:
            List of operator NOC codes
        """
        url = f"{self.BASE_URL}/{self.username}/fleet-completion/{self.datasource}"
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            html = response.text
            
            soup = BeautifulSoup(html, "html.parser")
            
            # Look for operator links in the sidebar/nav
            operator_nocs = []
            
            # Pattern to find operator links like /nxx/fleet-completion/BUSTIM/BLUS
            pattern = re.compile(rf'/{re.escape(self.username)}/fleet-completion/{self.datasource}/([A-Z0-9]+)')
            
            for a in soup.find_all('a', href=True):
                match = pattern.search(a['href'])
                if match:
                    noc = match.group(1)
                    if noc not in operator_nocs:
                        operator_nocs.append(noc)
            
            return operator_nocs
            
        except requests.RequestException as e:
            print(f"Error fetching main page: {e}")
            return []
    
    def get_fleet_completion_url(self, operator_noc: str) -> str:
        """Build the URL for a fleet completion page."""
        return f"{self.BASE_URL}/{self.username}/fleet-completion/{self.datasource}/{operator_noc}"
    
    def fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch a page from TransitTracker.
        
        Args:
            url: URL to fetch
            
        Returns:
            HTML content or None if fetch fails
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def parse_fleet_completion_page(self, html: str, operator_noc: str) -> list[ScrapedVehicle]:
        """
        Parse a fleet completion page to extract vehicle registrations.
        
        Args:
            html: HTML content of the page
            operator_noc: Operator NOC code
            
        Returns:
            List of ScrapedVehicle objects
        """
        # Extract the URL from the HTML to use with Playwright
        soup = BeautifulSoup(html, "html.parser")
        canonical = soup.find('link', rel='canonical')
        if canonical:
            url = canonical.get('href')
        else:
            # Fallback: try to extract URL from og:url
            og_url = soup.find('meta', property='og:url')
            if og_url:
                url = og_url.get('content')
            else:
                # Last resort: use the URL from the request
                return self._extract_vehicles_from_html(html, operator_noc)
        
        # Try using Playwright to render JavaScript and wait for Livewire data
        if PLAYWRIGHT_AVAILABLE:
            try:
                return self._parse_with_playwright(url, operator_noc)
            except Exception as e:
                print(f"Error using Playwright: {e}")
                import traceback
                traceback.print_exc()
        
        # Fallback: Look for registration patterns in text
        return self._extract_vehicles_from_html(html, operator_noc)
    
    def _parse_with_playwright(self, url: str, operator_noc: str) -> list[ScrapedVehicle]:
        """
        Use Playwright to render JavaScript and extract vehicle data.
        
        Args:
            url: URL of the fleet completion page
            operator_noc: Operator NOC code
            
        Returns:
            List of ScrapedVehicle objects
        """
        vehicles = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            try:
                page.goto(url, wait_until='networkidle')
                
                # Wait for the Livewire component to load data
                # Wait for the loading spinner to disappear
                page.wait_for_selector('div:not([class*="animate-spin"])', timeout=10000)
                
                # Wait a bit more for data to fully load
                time.sleep(2)
                
                # Get the rendered HTML
                html_content = page.content()
                
                # Extract vehicles from the rendered HTML
                vehicles = self._extract_vehicles_from_html(html_content, operator_noc)
                
            finally:
                browser.close()
        
        return vehicles
    
    def _extract_reg_from_dict(self, data: dict) -> Optional[str]:
        """Extract registration from a dictionary using common key names."""
        for reg_key in ['registration', 'reg', 'vrn', 'plate', 'fleet_code']:
            if reg_key in data:
                reg = str(data[reg_key]).upper().replace(" ", "")
                if len(reg) >= 5:
                    return reg
        return None
    
    def _get_csrf_token(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract CSRF token from the page."""
        # Look for CSRF token in Livewire script tag
        livewire_script = soup.find('script', attrs={'data-csrf': True})
        if livewire_script:
            return livewire_script.get('data-csrf')
        
        # Look for CSRF token in meta tags
        csrf_meta = soup.find('meta', attrs={'name': 'csrf-token'})
        if csrf_meta:
            return csrf_meta.get('content')
        
        # Look for CSRF token in input fields
        csrf_input = soup.find('input', attrs={'name': '_token'})
        if csrf_input:
            return csrf_input.get('value')
        
        return None
    
    def _extract_vehicles_from_html(self, html: str, operator_noc: str) -> list[ScrapedVehicle]:
        """
        Extract vehicle registrations from HTML content.
        
        Args:
            html: HTML content
            operator_noc: Operator NOC code
            
        Returns:
            List of ScrapedVehicle objects
        """
        vehicles = []
        soup = BeautifulSoup(html, "html.parser")
        
        # Multiple patterns to catch different registration formats
        # UK registration pattern: e.g., "AB12 CDE", "AB12CDE", "A123 BCD"
        reg_pattern = re.compile(r'\b([A-Z]{1,2}\d{1,4}[A-Z]{3})\b', re.IGNORECASE)
        
        # Also look for patterns with spaces: "AB12 CDE"
        reg_pattern_with_space = re.compile(r'\b([A-Z]{1,2}\d{1,4}\s?[A-Z]{3})\b', re.IGNORECASE)
        
        # Also look for fleet numbers that might be registrations
        fleet_pattern = re.compile(r'\b(\d{3,4})\b', re.IGNORECASE)
        
        # Search all text nodes for registration patterns
        for text in soup.stripped_strings:
            # Try full registration pattern first
            matches = reg_pattern.findall(text)
            for match in matches:
                reg = match.upper().replace(" ", "")
                if reg and len(reg) >= 5:  # Basic validation
                    vehicles.append(ScrapedVehicle(registration=reg, operator_noc=operator_noc))
            
            # Try pattern with space
            matches_with_space = reg_pattern_with_space.findall(text)
            for match in matches_with_space:
                reg = match.upper().replace(" ", "")
                if reg and len(reg) >= 5:  # Basic validation
                    vehicles.append(ScrapedVehicle(registration=reg, operator_noc=operator_noc))
        
        # Deduplicate vehicles by registration
        seen_regs = set()
        unique_vehicles = []
        for vehicle in vehicles:
            if vehicle.registration not in seen_regs:
                seen_regs.add(vehicle.registration)
                unique_vehicles.append(vehicle)
        
        return unique_vehicles
    
    def scrape_operator(self, operator_noc: str) -> list[ScrapedVehicle]:
        """
        Scrape a single operator's fleet completion page.
        
        Args:
            operator_noc: Operator NOC code
            
        Returns:
            List of ScrapedVehicle objects
        """
        url = self.get_fleet_completion_url(operator_noc)
        print(f"Fetching: {url}")
        
        html = self.fetch_page(url)
        if not html:
            return []
        
        vehicles = self.parse_fleet_completion_page(html, operator_noc)
        print(f"Found {len(vehicles)} vehicles for {operator_noc}")
        
        # Be polite to the server
        time.sleep(1)
        
        return vehicles
    
    def scrape_operators(self, operator_nocs: list[str]) -> dict[str, list[ScrapedVehicle]]:
        """
        Scrape multiple operators' fleet completion pages.
        
        Args:
            operator_nocs: List of operator NOC codes
            
        Returns:
            Dictionary mapping operator NOC to list of ScrapedVehicle objects
        """
        results = {}
        
        for operator_noc in operator_nocs:
            vehicles = self.scrape_operator(operator_noc)
            if vehicles:
                results[operator_noc] = vehicles
        
        return results


def match_vehicle_to_database(
    scraped_vehicle: ScrapedVehicle,
    operator_noc: Optional[str] = None
) -> Optional[Vehicle]:
    """
    Match a scraped vehicle to a Vehicle in the database.
    
    Args:
        scraped_vehicle: ScrapedVehicle object
        operator_noc: Optional operator NOC to narrow search
        
    Returns:
        Vehicle object or None if no match found
    """
    reg = scraped_vehicle.registration.upper().replace(" ", "")
    
    # Try to match by registration first
    queryset = Vehicle.objects.filter(reg__iexact=reg)
    
    # If operator is specified, filter by operator
    if operator_noc:
        operator = Operator.objects.filter(noc__iexact=operator_noc).first()
        if operator:
            queryset = queryset.filter(operator=operator)
    
    vehicle = queryset.first()
    
    if vehicle:
        return vehicle
    
    # Try to match by fleet number if available
    if scraped_vehicle.fleet_number:
        queryset = Vehicle.objects.filter(fleet_number=scraped_vehicle.fleet_number)
        if operator_noc:
            operator = Operator.objects.filter(noc__iexact=operator_noc).first()
            if operator:
                queryset = queryset.filter(operator=operator)
        vehicle = queryset.first()
        if vehicle:
            return vehicle
    
    return None


def import_ridden_logs(
    user: User,
    scraped_vehicles: list[ScrapedVehicle],
    operator_noc: Optional[str] = None,
    dry_run: bool = False
) -> dict[str, int]:
    """
    Import ridden logs from scraped vehicles.
    
    Args:
        user: User to create ride logs for
        scraped_vehicles: List of ScrapedVehicle objects
        operator_noc: Optional operator NOC for matching
        dry_run: If True, don't actually create records
        
    Returns:
        Dictionary with statistics: {'matched': int, 'created': int, 'skipped': int, 'errors': int}
    """
    stats = {
        'matched': 0,
        'created': 0,
        'skipped': 0,
        'errors': 0
    }
    
    for scraped_vehicle in scraped_vehicles:
        try:
            vehicle = match_vehicle_to_database(scraped_vehicle, operator_noc)
            
            if not vehicle:
                stats['skipped'] += 1
                print(f"Skipped: No match for registration {scraped_vehicle.registration}")
                continue
            
            stats['matched'] += 1
            
            # Check if ride log already exists
            existing = FleetRideLog.objects.filter(user=user, vehicle=vehicle).exists()
            
            if existing:
                stats['skipped'] += 1
                print(f"Skipped: Ride log already exists for {vehicle}")
                continue
            
            if not dry_run:
                with transaction.atomic():
                    FleetRideLog.objects.create(user=user, vehicle=vehicle)
                stats['created'] += 1
                print(f"Created ride log for {vehicle}")
            else:
                stats['created'] += 1
                print(f"[DRY RUN] Would create ride log for {vehicle}")
                
        except Exception as e:
            stats['errors'] += 1
            print(f"Error processing {scraped_vehicle.registration}: {e}")
    
    return stats


def run_import(
    transittracker_username: str,
    user: User,
    operator_nocs: list[str],
    datasource: str = "BUSTIM",
    dry_run: bool = False
) -> dict[str, any]:
    """
    Run a complete import from TransitTracker.
    
    Args:
        transittracker_username: TransitTracker username to scrape
        user: User to create ride logs for
        operator_nocs: List of operator NOC codes to scrape
        datasource: Data source (default: BUSTIM)
        dry_run: If True, don't actually create records
        
    Returns:
        Dictionary with import results and statistics
    """
    scraper = TransitTrackerScraper(transittracker_username, datasource)
    
    print(f"Starting import from TransitTracker user: {transittracker_username}")
    print(f"Operators to scrape: {', '.join(operator_nocs)}")
    
    # Scrape all operators
    scraped_data = scraper.scrape_operators(operator_nocs)
    
    total_stats = {
        'matched': 0,
        'created': 0,
        'skipped': 0,
        'errors': 0,
        'operators_scraped': len(scraped_data),
        'total_vehicles_found': sum(len(v) for v in scraped_data.values())
    }
    
    # Import for each operator
    for operator_noc, vehicles in scraped_data.items():
        print(f"\nProcessing operator {operator_noc}:")
        stats = import_ridden_logs(user, vehicles, operator_noc, dry_run)
        
        for key in total_stats:
            if key in stats:
                total_stats[key] += stats[key]
    
    print(f"\nImport complete!")
    print(f"Operators scraped: {total_stats['operators_scraped']}")
    print(f"Total vehicles found: {total_stats['total_vehicles_found']}")
    print(f"Matched to database: {total_stats['matched']}")
    print(f"Ride logs created: {total_stats['created']}")
    print(f"Skipped: {total_stats['skipped']}")
    print(f"Errors: {total_stats['errors']}")
    
    return total_stats
