"""
Tests for fleet API endpoints.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from vehicles.models import Vehicle, Livery
from busstops.models import Operator
from fleet.models import LiveVehicleLocation


class LiveTrackingJsonTests(TestCase):
    """Tests for the /fleet/live-tracking.json endpoint."""

    def setUp(self):
        """Set up test data."""
        self.operator = Operator.objects.create(name="Test Operator", noc="TEST")
        self.livery = Livery.objects.create(
            name="Test Livery",
            colour="#ff0000",
            left_css="background: #ff0000;",
        )
        self.vehicle = Vehicle.objects.create(
            code="TEST123",
            operator=self.operator,
            livery=self.livery,
            reg="ABC123",
        )

    def test_empty_response(self):
        """Test response when no vehicles are tracked."""
        response = self.client.get('/fleet/live-tracking.json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_single_vehicle(self):
        """Test response with one tracked vehicle."""
        LiveVehicleLocation.objects.create(
            vehicle=self.vehicle,
            latitude=51.5,
            longitude=-0.1,
            heading=90,
            destination="Test Destination",
        )

        response = self.client.get('/fleet/live-tracking.json')
        self.assertEqual(response.status_code, 200)
        
        vehicles = response.json()
        self.assertEqual(len(vehicles), 1)
        
        vehicle_data = vehicles[0]
        self.assertEqual(vehicle_data['id'], self.vehicle.id)
        self.assertEqual(vehicle_data['coordinates'], [-0.1, 51.5])
        self.assertEqual(vehicle_data['heading'], 90)
        self.assertEqual(vehicle_data['destination'], "Test Destination")
        self.assertEqual(vehicle_data['source'], "manual")
        self.assertTrue(vehicle_data['is_manual'])

    def test_vehicle_schema_compatibility(self):
        """Test that response schema matches vehicles.json format."""
        LiveVehicleLocation.objects.create(
            vehicle=self.vehicle,
            latitude=51.5,
            longitude=-0.1,
            heading=90,
        )

        response = self.client.get('/fleet/live-tracking.json')
        vehicle_data = response.json()[0]
        
        # Check required fields
        self.assertIn('id', vehicle_data)
        self.assertIn('coordinates', vehicle_data)
        self.assertIn('vehicle', vehicle_data)
        self.assertIn('source', vehicle_data)
        
        # Check vehicle sub-object
        self.assertIn('id', vehicle_data['vehicle'])
        self.assertIn('reg', vehicle_data['vehicle'])
        self.assertIn('colour', vehicle_data['vehicle'])
        self.assertIn('css', vehicle_data['vehicle'])

    def test_multiple_vehicles(self):
        """Test response with multiple tracked vehicles."""
        vehicle2 = Vehicle.objects.create(
            code="TEST456",
            operator=self.operator,
            livery=self.livery,
            reg="DEF456",
        )
        
        LiveVehicleLocation.objects.create(
            vehicle=self.vehicle,
            latitude=51.5,
            longitude=-0.1,
        )
        LiveVehicleLocation.objects.create(
            vehicle=vehicle2,
            latitude=51.6,
            longitude=-0.2,
        )

        response = self.client.get('/fleet/live-tracking.json')
        vehicles = response.json()
        self.assertEqual(len(vehicles), 2)

    def test_optional_fields(self):
        """Test handling of optional fields."""
        LiveVehicleLocation.objects.create(
            vehicle=self.vehicle,
            latitude=51.5,
            longitude=-0.1,
            heading=None,  # Optional
            destination="",  # Empty
            lateness=5,  # Optional
        )

        response = self.client.get('/fleet/live-tracking.json')
        vehicle_data = response.json()[0]
        
        self.assertIsNone(vehicle_data['heading'])
        self.assertEqual(vehicle_data['destination'], "")
        self.assertEqual(vehicle_data['delay'], 5)

    def test_cache_headers(self):
        """Test that response has no-cache headers."""
        LiveVehicleLocation.objects.create(
            vehicle=self.vehicle,
            latitude=51.5,
            longitude=-0.1,
        )

        response = self.client.get('/fleet/live-tracking.json')
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
