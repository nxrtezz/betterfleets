import json
from datetime import datetime, timedelta, timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from busstops.models import Operator, StopPoint
from bustimes.models import StopTime, Trip
from fleet.models import OverlandSubscription
from vehicles.models import Vehicle, VehicleJourney


class OverlandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="overland-user",
            password="password",
        )
        self.operator = Operator.objects.create(name="Test Operator", noc="TEST")
        self.vehicle = Vehicle.objects.create(
            code="TEST123",
            operator=self.operator,
            reg="ABC123",
        )
        self.client.force_login(self.user)
        self.stops = [
            StopPoint.objects.create(
                atco_code=f"STP{i}",
                common_name=f"Stop {i}",
                active=True,
            )
            for i in (1, 2)
        ]

    def grant_overland_permission(self):
        permission = Permission.objects.get(
            content_type__app_label="fleet",
            codename="use_overland",
        )
        self.user.user_permissions.add(permission)

    def test_generator_requires_overland_permission(self):
        response = self.client.get(reverse("overland_generator"))
        self.assertEqual(response.status_code, 403)

    def test_generator_returns_authenticated_endpoint(self):
        self.grant_overland_permission()
        response = self.client.post(
            reverse("overland_generator"),
            {
                "vehicle_slug": self.vehicle.slug,
                "destination": "Town",
                "route_number": "1",
                "trip_id": "42",
            },
        )
        self.assertEqual(response.status_code, 200)
        subscription = OverlandSubscription.objects.get()
        endpoint = response.context["endpoint"]
        self.assertIn(f"/overland/{subscription.uuid}", endpoint)
        self.assertIn("auth=", endpoint)
        self.assertEqual(subscription.destination, "Town")
        self.assertIsNotNone(subscription.journey_id)

    def test_generator_creates_scheduled_trip_and_journey(self):
        self.grant_overland_permission()
        response = self.client.post(
            reverse("overland_generator"),
            {
                "vehicle_slug": self.vehicle.slug,
                "destination": "Town",
                "route_number": "1",
                "tracking_date": "2026-10-02",
                "stop_id": [stop.atco_code for stop in self.stops],
                "arrival_time": ["09:00", "09:30"],
                "departure_time": ["09:05", "09:35"],
            },
        )
        self.assertEqual(response.status_code, 200)
        subscription = OverlandSubscription.objects.get()
        self.assertIsNotNone(subscription.scheduled_trip_id)
        self.assertEqual(subscription.journey.trip_id, subscription.scheduled_trip_id)
        self.assertEqual(
            list(
                StopTime.objects.filter(trip=subscription.scheduled_trip)
                .values_list("stop_id", "arrival", "departure")
            ),
            [
                ("STP1", timedelta(hours=9), timedelta(hours=9, minutes=5)),
                ("STP2", timedelta(hours=9, minutes=30), timedelta(hours=9, minutes=35)),
            ],
        )
        self.assertEqual(
            Trip.objects.get(pk=subscription.scheduled_trip_id).calendar.start_date.isoformat(),
            "2026-10-02",
        )
        self.assertTrue(VehicleJourney.objects.filter(pk=subscription.journey_id).exists())

    def test_ingest_requires_auth_and_updates_feed(self):
        secret = "test-secret"
        subscription = OverlandSubscription.objects.create(
            user=self.user,
            vehicle=self.vehicle,
            destination="Town",
            route_number="1",
            trip_id="42",
            auth_key_hash=OverlandSubscription.hash_auth_key(secret),
        )
        payload = {
            "locations": [
                {
                    "geometry": {"coordinates": [-1.2, 52.3]},
                    "properties": {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "course": 91.4,
                    },
                }
            ]
        }
        denied = self.client.post(
            f"/overland/{subscription.uuid}",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)

        accepted = self.client.post(
            f"/overland/{subscription.uuid}?auth={secret}",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(accepted.status_code, 200)
        response = self.client.get("/overland.json")
        item = response.json()[0]
        self.assertEqual(item["coordinates"], [-1.2, 52.3])
        self.assertEqual(item["heading"], 91)
        self.assertEqual(item["source"], "overland")
