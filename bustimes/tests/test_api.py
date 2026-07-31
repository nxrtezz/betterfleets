"""
Tests for bustimes API endpoints.
"""

from django.test import TestCase
from django.urls import reverse


class SimulatedVehiclesJsonTests(TestCase):
    """Tests for the /simulated-vehicles.json endpoint."""

    def test_empty_response(self):
        """Test response when no routes are configured."""
        response = self.client.get('/simulated-vehicles.json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_response_format(self):
        """Test that response has correct format."""
        response = self.client.get('/simulated-vehicles.json')
        # Should return a list
        self.assertIsInstance(response.json(), list)

    def test_cache_headers(self):
        """Test that response has no-cache headers."""
        response = self.client.get('/simulated-vehicles.json')
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])

    def test_source_metadata(self):
        """Test that vehicles have source metadata when returned."""
        # This test would need configured simulation routes to be meaningful
        # For now, just check the endpoint exists
        response = self.client.get('/simulated-vehicles.json')
        self.assertEqual(response.status_code, 200)
