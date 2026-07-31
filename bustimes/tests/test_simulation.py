"""
Tests for the simulation engine.
"""

from datetime import datetime, timedelta, time, date
from decimal import Decimal
from django.test import TestCase
from django.contrib.gis.geos import Point
from django.utils import timezone
from unittest.mock import patch, MagicMock

from bustimes.simulation import (
    get_active_trip_for_service,
    interpolate_position,
    calculate_heading,
    get_simulated_vehicle_position,
    get_all_simulated_vehicles,
    validate_simulation_routes,
    SIMULATION_ROUTES,
)
from bustimes.models import Trip, StopTime, Route, Calendar
from busstops.models import Service, StopPoint, Operator


class SimulationValidationTests(TestCase):
    """Tests for simulation route configuration validation."""

    def test_valid_configuration(self):
        """Test that a valid configuration passes validation."""
        with patch('bustimes.simulation.SIMULATION_ROUTES', {
            'test-route': {
                'service_id': 123,
                'vehicle_type': 'ferry',
                'default_vehicle': {
                    'id': -1,
                    'reg': 'SIM001',
                    'name': 'Simulated Ferry',
                }
            }
        }):
            errors = validate_simulation_routes()
            self.assertEqual(errors, [])

    def test_missing_service_id(self):
        """Test that missing service_id is caught."""
        with patch('bustimes.simulation.SIMULATION_ROUTES', {
            'test-route': {
                'vehicle_type': 'ferry',
            }
        }):
            errors = validate_simulation_routes()
            self.assertIn("missing required field 'service_id'", errors[0])

    def test_invalid_service_id_type(self):
        """Test that non-integer service_id is caught."""
        with patch('bustimes.simulation.SIMULATION_ROUTES', {
            'test-route': {
                'service_id': "123",
            }
        }):
            errors = validate_simulation_routes()
            self.assertIn("'service_id' must be an integer", errors[0])

    def test_invalid_vehicle_config(self):
        """Test that invalid vehicle config is caught."""
        with patch('bustimes.simulation.SIMULATION_ROUTES', {
            'test-route': {
                'service_id': 123,
                'default_vehicle': "not a dict",
            }
        }):
            errors = validate_simulation_routes()
            self.assertIn("'default_vehicle' must be a dictionary", errors[0])


class InterpolationTests(TestCase):
    """Tests for position interpolation."""

    def setUp(self):
        """Set up test data."""
        self.trip_date = date(2024, 1, 15)
        self.point_a = Point(-0.1, 51.5)
        self.point_b = Point(-0.2, 51.6)

    def test_basic_interpolation(self):
        """Test basic linear interpolation between two points."""
        stop_a = MagicMock()
        stop_a.stop = MagicMock()
        stop_a.stop.location = self.point_a
        stop_a.departure_datetime = lambda d: datetime(2024, 1, 15, 10, 0)

        stop_b = MagicMock()
        stop_b.stop = MagicMock()
        stop_b.stop.location = self.point_b
        stop_b.arrival_datetime = lambda d: datetime(2024, 1, 15, 10, 30)

        current_time = datetime(2024, 1, 15, 10, 15)  # Halfway

        result = interpolate_position(stop_a, stop_b, current_time, self.trip_date)
        
        self.assertIsNotNone(result)
        # Should be halfway between points
        self.assertAlmostEqual(result.x, -0.15, places=5)
        self.assertAlmostEqual(result.y, 51.55, places=5)

    def test_before_start(self):
        """Test position before trip start returns start point."""
        stop_a = MagicMock()
        stop_a.stop = MagicMock()
        stop_a.stop.location = self.point_a
        stop_a.departure_datetime = lambda d: datetime(2024, 1, 15, 10, 0)

        stop_b = MagicMock()
        stop_b.stop = MagicMock()
        stop_b.stop.location = self.point_b
        stop_b.arrival_datetime = lambda d: datetime(2024, 1, 15, 10, 30)

        current_time = datetime(2024, 1, 15, 9, 30)  # Before start

        result = interpolate_position(stop_a, stop_b, current_time, self.trip_date)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.x, self.point_a.x)
        self.assertEqual(result.y, self.point_a.y)

    def test_after_end(self):
        """Test position after trip end returns end point."""
        stop_a = MagicMock()
        stop_a.stop = MagicMock()
        stop_a.stop.location = self.point_a
        stop_a.departure_datetime = lambda d: datetime(2024, 1, 15, 10, 0)

        stop_b = MagicMock()
        stop_b.stop = MagicMock()
        stop_b.stop.location = self.point_b
        stop_b.arrival_datetime = lambda d: datetime(2024, 1, 15, 10, 30)

        current_time = datetime(2024, 1, 15, 11, 0)  # After end

        result = interpolate_position(stop_a, stop_b, current_time, self.trip_date)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.x, self.point_b.x)
        self.assertEqual(result.y, self.point_b.y)

    def test_missing_stop_coordinates(self):
        """Test that missing stop coordinates return None."""
        stop_a = MagicMock()
        stop_a.stop = None

        stop_b = MagicMock()
        stop_b.stop = MagicMock()
        stop_b.stop.location = self.point_b

        current_time = datetime(2024, 1, 15, 10, 15)

        result = interpolate_position(stop_a, stop_b, current_time, self.trip_date)
        self.assertIsNone(result)

    def test_missing_location_data(self):
        """Test that stops without location data return None."""
        stop_a = MagicMock()
        stop_a.stop = MagicMock()
        stop_a.stop.location = None
        stop_a.departure_datetime = lambda d: datetime(2024, 1, 15, 10, 0)

        stop_b = MagicMock()
        stop_b.stop = MagicMock()
        stop_b.stop.location = self.point_b
        stop_b.arrival_datetime = lambda d: datetime(2024, 1, 15, 10, 30)

        current_time = datetime(2024, 1, 15, 10, 15)

        result = interpolate_position(stop_a, stop_b, current_time, self.trip_date)
        self.assertIsNone(result)

    def test_invalid_time_range(self):
        """Test that invalid time ranges (start >= end) return None."""
        stop_a = MagicMock()
        stop_a.stop = MagicMock()
        stop_a.stop.location = self.point_a
        stop_a.departure_datetime = lambda d: datetime(2024, 1, 15, 10, 30)

        stop_b = MagicMock()
        stop_b.stop = MagicMock()
        stop_b.stop.location = self.point_b
        stop_b.arrival_datetime = lambda d: datetime(2024, 1, 15, 10, 0)

        current_time = datetime(2024, 1, 15, 10, 15)

        result = interpolate_position(stop_a, stop_b, current_time, self.trip_date)
        self.assertIsNone(result)


class HeadingCalculationTests(TestCase):
    """Tests for heading calculation."""

    def test_north_heading(self):
        """Test heading calculation for northward movement."""
        point_a = Point(0, 0)
        point_b = Point(0, 1)
        heading = calculate_heading(point_a, point_b)
        self.assertAlmostEqual(heading, 0, places=1)

    def test_east_heading(self):
        """Test heading calculation for eastward movement."""
        point_a = Point(0, 0)
        point_b = Point(1, 0)
        heading = calculate_heading(point_a, point_b)
        self.assertAlmostEqual(heading, 90, places=1)

    def test_south_heading(self):
        """Test heading calculation for southward movement."""
        point_a = Point(0, 1)
        point_b = Point(0, 0)
        heading = calculate_heading(point_a, point_b)
        self.assertAlmostEqual(heading, 180, places=1)

    def test_west_heading(self):
        """Test heading calculation for westward movement."""
        point_a = Point(1, 0)
        point_b = Point(0, 0)
        heading = calculate_heading(point_a, point_b)
        self.assertAlmostEqual(heading, 270, places=1)

    def test_diagonal_heading(self):
        """Test heading calculation for diagonal movement."""
        point_a = Point(0, 0)
        point_b = Point(1, 1)
        heading = calculate_heading(point_a, point_b)
        self.assertAlmostEqual(heading, 45, places=1)


class ActiveTripDetectionTests(TestCase):
    """Tests for active trip detection."""

    def setUp(self):
        """Set up test data."""
        self.operator = Operator.objects.create(name="Test Operator", noc="TEST")
        self.service = Service.objects.create(
            operator=self.operator,
            line_name="Test Service",
            slug="test-service",
        )
        self.calendar = Calendar.objects.create(
            mon=True,
            tue=True,
            wed=True,
            thu=True,
            fri=True,
            sat=True,
            sun=True,
            start_date=date(2024, 1, 1),
        )
        self.route = Route.objects.create(
            service=self.service,
            line_name="Test Route",
        )

    def test_active_trip_during_service(self):
        """Test detection of trip during its scheduled time."""
        trip = Trip.objects.create(
            route=self.route,
            calendar=self.calendar,
            start=timedelta(hours=10),
            end=timedelta(hours=11),
        )

        current_time = datetime(2024, 1, 15, 10, 30)
        result = get_active_trip_for_service(self.service.id, current_time)
        
        self.assertEqual(result, trip)

    def test_no_active_trip_before_start(self):
        """Test that no trip is detected before service start."""
        Trip.objects.create(
            route=self.route,
            calendar=self.calendar,
            start=timedelta(hours=10),
            end=timedelta(hours=11),
        )

        current_time = datetime(2024, 1, 15, 9, 30)
        result = get_active_trip_for_service(self.service.id, current_time)
        
        self.assertIsNone(result)

    def test_no_active_trip_after_end(self):
        """Test that no trip is detected after service end."""
        Trip.objects.create(
            route=self.route,
            calendar=self.calendar,
            start=timedelta(hours=10),
            end=timedelta(hours=11),
        )

        current_time = datetime(2024, 1, 15, 12, 0)
        result = get_active_trip_for_service(self.service.id, current_time)
        
        self.assertIsNone(result)

    def test_overnight_trip(self):
        """Test detection of overnight trip."""
        trip = Trip.objects.create(
            route=self.route,
            calendar=self.calendar,
            start=timedelta(hours=23),
            end=timedelta(hours=1),  # Next day
        )

        current_time = datetime(2024, 1, 15, 23, 30)
        result = get_active_trip_for_service(self.service.id, current_time)
        
        self.assertEqual(result, trip)

    def test_overnight_trip_next_day(self):
        """Test detection of overnight trip early next morning."""
        trip = Trip.objects.create(
            route=self.route,
            calendar=self.calendar,
            start=timedelta(hours=23),
            end=timedelta(hours=1),  # Next day
        )

        current_time = datetime(2024, 1, 16, 0, 30)
        result = get_active_trip_for_service(self.service.id, current_time)
        
        self.assertEqual(result, trip)

    def test_calendar_not_allowed(self):
        """Test that trips not allowed by calendar are not detected."""
        # Calendar that doesn't allow Mondays
        calendar = Calendar.objects.create(
            mon=False,
            tue=True,
            wed=True,
            thu=True,
            fri=True,
            sat=True,
            sun=True,
            start_date=date(2024, 1, 1),
        )
        
        Trip.objects.create(
            route=self.route,
            calendar=calendar,
            start=timedelta(hours=10),
            end=timedelta(hours=11),
        )

        # Monday
        current_time = datetime(2024, 1, 15, 10, 30)
        result = get_active_trip_for_service(self.service.id, current_time)
        
        self.assertIsNone(result)


class GetAllSimulatedVehiclesTests(TestCase):
    """Tests for getting all simulated vehicles."""

    def test_empty_configuration(self):
        """Test with no configured routes."""
        with patch('bustimes.simulation.SIMULATION_ROUTES', {}):
            vehicles = get_all_simulated_vehicles()
            self.assertEqual(vehicles, [])

    def test_invalid_configuration_logged(self):
        """Test that invalid configuration is logged."""
        with patch('bustimes.simulation.SIMULATION_ROUTES', {
            'invalid-route': {}
        }):
            with patch('bustimes.simulation.logger') as mock_logger:
                vehicles = get_all_simulated_vehicles()
                mock_logger.warning.assert_called()
                self.assertEqual(vehicles, [])
