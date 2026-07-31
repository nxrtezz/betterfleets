import datetime
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from busstops.models import DataSource, Operator, Service, ServiceCode
from bustimes.models import Garage
from vehicles.forms import EditVehicleForm
from vehicles.utils import apply_revision, get_revision

from .models import Vehicle, VehicleCode, VehicleFeature, VehicleJourney, VehicleReview, VehicleType
from .tasks import refresh_dvla_tax_statuses


@override_settings(BUSTIMES_VEHICLES_JSON_URL="https://example.test/vehicles.json")
class BustimesVehicleJsonTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(
            name="Bustimes API", url="https://bustimes.org/api/"
        )
        self.operator = Operator.objects.create(
            noc="FHAM",
            name="Fareham Buses",
            slug="fareham-buses",
        )
        VehicleFeature.objects.create(id=8, name="Fleet Support")
        self.vehicle = Vehicle.objects.create(
            code="47573",
            fleet_code="47573",
            reg="SN14EBG",
            operator=self.operator,
        )
        VehicleCode.objects.create(
            scheme="bustimes", code="remote-vehicle-47573", vehicle=self.vehicle
        )
        VehicleCode.objects.create(
            scheme="bustimes-slug", code="fham-47424", vehicle=self.vehicle
        )
        self.service = Service.objects.create(
            service_code="28A",
            line_name="28A",
            description="Fareham Bus Station - North Whiteley, Skipper Road",
            source=self.source,
        )
        ServiceCode.objects.create(
            service=self.service,
            scheme="bustimes-slug",
            code="28a-fareham-bus-station-botley-station",
        )
        self.journey = VehicleJourney.objects.create(
            source=self.source,
            vehicle=self.vehicle,
            service=self.service,
            code="remote-journey-302",
            datetime=timezone.make_aware(datetime.datetime(2026, 4, 18, 7, 51)),
            date=datetime.date(2026, 4, 18),
            route_name="28A",
            destination="Fareham",
        )
        self.vehicle.latest_journey = self.journey
        self.vehicle.save(update_fields=["latest_journey"])

    @patch("vehicles.views.requests.get")
    def test_vehicles_json_maps_bustimes_ids_to_local_rows(self, mock_get):
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "id": "remote-vehicle-47573",
                "journey_id": "remote-journey-302",
                "coordinates": [-1.18, 50.85],
                "heading": 90,
                "datetime": "2026-04-18T07:55:00+01:00",
                "destination": "Fareham",
                "service": {"line_name": "28A"},
            }
        ]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        response = self.client.get(f"/vehicles.json?id={self.vehicle.id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], self.vehicle.id)
        self.assertEqual(payload[0]["journey_id"], self.journey.id)
        self.assertEqual(payload[0]["vehicle"]["url"], self.vehicle.get_absolute_url())
        self.assertEqual(payload[0]["service"]["line_name"], "28A")
        self.assertEqual(mock_get.call_args.kwargs["params"]["id"], "remote-vehicle-47573")

    def test_journey_json_exposes_bustimes_map_shape(self):
        response = self.client.get(f"/journeys/{self.journey.id}.json")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["vehicle_id"], self.vehicle.id)
        self.assertEqual(payload["datetime"], "2026-04-18T07:51:00+01:00")
        self.assertEqual(payload["route_name"], "28A")
        self.assertEqual(payload["code"], "remote-journey-302")
        self.assertEqual(payload["destination"], "Fareham")
        self.assertTrue(payload["current"])

    def test_vehicle_detail_renders_journey_table(self):
        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertContains(response, "28A")
        self.assertContains(response, "remote-journey-302")
        self.assertContains(response, "Fareham")

    def test_vehicle_detail_accepts_bustimes_slug(self):
        response = self.client.get("/vehicles/fham-47424")

        self.assertContains(response, "28A")
        self.assertContains(response, "remote-journey-302")
        self.assertContains(response, "Fareham")

    def test_service_vehicle_history_accepts_bustimes_slug(self):
        response = self.client.get(
            "/services/28a-fareham-bus-station-botley-station/vehicles",
            {"date": "2026-04-18"},
        )

        self.assertContains(response, "47573 - SN14 EBG")
        self.assertContains(response, "remote-journey-302")
        self.assertContains(response, "Fareham")

    def test_operator_fleet_excludes_historical_fleet_vehicles(self):
        Vehicle.objects.create(
            code="HIST",
            fleet_code="1",
            reg="SK63KMU",
            operator=self.operator,
            historical_fleet=self.operator,
        )

        response = self.client.get("/operators/fareham-buses/vehicles")

        self.assertContains(response, "47573")
        self.assertNotContains(response, "SK63 KMU")

    def test_operator_historical_fleet_lists_historical_vehicles(self):
        historical_operator = Operator.objects.create(
            noc="HIST",
            name="Fareham Heritage",
            slug="fareham-heritage",
            preserved=True,
        )
        Vehicle.objects.create(
            code="HIST",
            fleet_code="1",
            reg="SK63KMU",
            operator=historical_operator,
            historical_fleet=self.operator,
        )

        response = self.client.get("/operators/fareham-buses/vehicles/historical")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historical fleets")
        self.assertContains(response, "SK63 KMU")
        self.assertContains(response, "Fareham Heritage")
        self.assertNotContains(response, "47573")

    def test_operator_historical_fleet_lists_same_operator_historical_year(self):
        vehicle = Vehicle.objects.create(
            code="H2005",
            fleet_code="2005",
            reg="SK63KMU",
            operator=self.operator,
            historical_fleet=self.operator,
            historical_fleet_year=2005,
            historical_fleet_creator="Fleet Curator",
        )

        response = self.client.get("/operators/fareham-buses/vehicles/historical")

        self.assertContains(response, "2005")
        self.assertContains(response, "SK63 KMU")
        self.assertContains(response, "Fareham Buses")
        self.assertContains(response, "Created by Fleet Curator")
        self.assertContains(response, "1 vehicle")
        self.assertIn("-2005", vehicle.slug)

    def test_vehicle_detail_shows_statuses(self):
        self.vehicle.preserved = True
        self.vehicle.vor = True
        self.vehicle.awaiting_delivery = True
        self.vehicle.save(
            update_fields=["preserved", "vor", "awaiting_delivery"]
        )

        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertContains(response, "Status")
        self.assertContains(response, "Preserved, VOR, Awaiting delivery")

    def test_vehicle_detail_shows_rear_advert_and_accessibility(self):
        VehicleFeature.objects.create(
            name="Wheelchair bay", category=VehicleFeature.Category.ACCESSIBILITY
        )
        self.vehicle.rear_advert = "Coastliner promo"
        self.vehicle.save(update_fields=["rear_advert"])
        self.vehicle.features.add(
            VehicleFeature.objects.get(name="Wheelchair bay")
        )

        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertContains(response, "Rear advert")
        self.assertContains(response, "Coastliner promo")
        self.assertContains(response, "Accessibility")
        self.assertContains(response, "Wheelchair bay")

    def test_operator_fleet_hides_rear_advert_data_column(self):
        self.vehicle.data = {
            "Rear advert": "Coastliner promo",
            "Body": "Enviro200",
        }
        self.vehicle.save(update_fields=["data"])

        response = self.client.get("/operators/fareham-buses/vehicles")

        self.assertContains(response, "Body")
        self.assertContains(response, "Enviro200")
        self.assertNotContains(response, "Rear advert")
        self.assertNotContains(response, "Coastliner promo")

    def test_blocked_review_is_held_for_moderation(self):
        reviewer = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com",
            password="secret",
        )
        self.client.force_login(reviewer)

        response = self.client.post(
            self.vehicle.get_absolute_url(),
            {"rating": "4.5", "message": "That driver is a nigger."},
        )

        review = VehicleReview.objects.get(vehicle=self.vehicle, user=reviewer)
        self.assertEqual(review.status, VehicleReview.Status.PENDING)
        self.assertIn("nigger", review.flagged_terms)
        self.assertNotContains(response, "That driver is a nigger.")

    def test_review_report_creates_report_and_hides_review(self):
        review_author = User.objects.create_user(
            username="author",
            email="author@example.com",
            password="secret",
        )
        reporter = User.objects.create_user(
            username="reporter",
            email="reporter@example.com",
            password="secret",
        )
        review = VehicleReview.objects.create(
            vehicle=self.vehicle,
            user=review_author,
            rating=Decimal("4.0"),
            message="Awful and abusive review",
        )
        self.client.force_login(reporter)

        response = self.client.post(
            self.vehicle.get_absolute_url(),
            {
                "report_review_id": str(review.id),
                "reason": "Contains abusive language",
            },
        )

        review.refresh_from_db()
        self.assertEqual(review.status, VehicleReview.Status.PENDING)
        self.assertEqual(review.reports.count(), 1)
        self.assertNotContains(response, "Awful and abusive review")

    def test_vehicle_reviews_appear_in_admin(self):
        admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secret",
        )
        VehicleReview.objects.create(
            vehicle=self.vehicle,
            user=admin_user,
            rating=Decimal("5.0"),
            message="Excellent bus.",
        )
        self.client.force_login(admin_user)

        response = self.client.get("/admin/vehicles/vehiclereview/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Excellent bus.")

    def test_review_delete_button_requires_permission(self):
        review_author = User.objects.create_user(
            username="author2",
            email="author2@example.com",
            password="secret",
        )
        manager = User.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="secret",
        )
        review = VehicleReview.objects.create(
            vehicle=self.vehicle,
            user=review_author,
            rating=Decimal("4.0"),
            message="Please remove me",
        )

        self.client.force_login(manager)
        response = self.client.get(self.vehicle.get_absolute_url())
        self.assertNotContains(response, "Delete review")

        manager.user_permissions.add(Permission.objects.get(codename="delete_review"))
        response = self.client.get(self.vehicle.get_absolute_url())
        self.assertContains(response, "Delete review")

        response = self.client.post(
            self.vehicle.get_absolute_url(),
            {"delete_review_id": str(review.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(VehicleReview.objects.filter(pk=review.pk).exists())

    def test_blocked_user_cannot_submit_review(self):
        blocked_user = User.objects.create_user(
            username="blocked-reviewer",
            email="blocked@example.com",
            password="secret",
            blocked_from_reviews=True,
        )
        self.client.force_login(blocked_user)

        response = self.client.get(self.vehicle.get_absolute_url())
        self.assertContains(response, "blocked from submitting reviews")
        self.assertNotContains(response, "Save review")

        response = self.client.post(
            self.vehicle.get_absolute_url(),
            {"rating": "4.5", "message": "Should not be saved"},
        )
        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            VehicleReview.objects.filter(vehicle=self.vehicle, user=blocked_user).exists()
        )

    def test_staff_review_moderation_page_can_publish_and_hide_reviews(self):
        staff_user = User.objects.create_user(
            username="staffer",
            email="staffer@example.com",
            password="secret",
            is_staff=True,
        )
        review_author = User.objects.create_user(
            username="queue-author",
            email="queue-author@example.com",
            password="secret",
        )
        review = VehicleReview.objects.create(
            vehicle=self.vehicle,
            user=review_author,
            rating=Decimal("3.5"),
            message="Needs review",
            status=VehicleReview.Status.PENDING,
        )

        self.client.force_login(staff_user)
        response = self.client.get("/staff/reviews")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review moderation")
        self.assertContains(response, "Needs review")

        self.client.post("/staff/reviews", {"review_id": str(review.id), "action": "publish"})
        review.refresh_from_db()
        self.assertEqual(review.status, VehicleReview.Status.PUBLISHED)

        self.client.post("/staff/reviews", {"review_id": str(review.id), "action": "hide"})
        review.refresh_from_db()
        self.assertEqual(review.status, VehicleReview.Status.HIDDEN)

    def test_vehicle_detail_shows_sorn_vor_suggestion(self):
        self.vehicle.dvla_tax_status = "SORN"
        self.vehicle.dvla_tax_status_checked_at = timezone.now()
        self.vehicle.save(
            update_fields=["dvla_tax_status", "dvla_tax_status_checked_at"]
        )

        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertContains(response, "marked as")
        self.assertContains(response, "SORN")
        self.assertContains(response, "may be VOR")

    def test_vehicle_detail_shows_dvla_euro_status(self):
        self.vehicle.dvla_euro_status = "EURO 6 AD"
        self.vehicle.save(update_fields=["dvla_euro_status"])

        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertContains(response, "Euro status")
        self.assertContains(response, "EURO 6 AD")

    def test_vehicle_detail_shows_dvla_mot_status(self):
        self.vehicle.dvla_mot_status = "Valid"
        self.vehicle.save(update_fields=["dvla_mot_status"])

        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertContains(response, "MOT status")
        self.assertContains(response, "Valid")

    def test_vehicle_detail_hides_sorn_vor_suggestion_for_vor_vehicle(self):
        self.vehicle.vor = True
        self.vehicle.dvla_tax_status = "SORN"
        self.vehicle.dvla_tax_status_checked_at = timezone.now()
        self.vehicle.save(
            update_fields=["vor", "dvla_tax_status", "dvla_tax_status_checked_at"]
        )

        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertNotContains(response, "may be VOR")

    def test_vehicle_edits_page_no_longer_shows_attention_filter(self):
        response = self.client.get("/vehicles/edits?status=approved&show=all")

        self.assertNotContains(response, "SORN not marked VOR/removed/preserved")

    def test_sorn_vehicles_page_shows_only_non_vor_non_withdrawn_non_preserved_by_default(self):
        matching_vehicle = Vehicle.objects.create(
            code="MATCH1",
            fleet_code="1001",
            reg="AB12CDE",
            operator=self.operator,
            dvla_tax_status="SORN",
            vor=False,
            withdrawn=False,
            preserved=False,
        )
        excluded_vor = Vehicle.objects.create(
            code="MATCH2",
            fleet_code="1002",
            reg="AB12CDF",
            operator=self.operator,
            dvla_tax_status="SORN",
            vor=True,
        )
        excluded_withdrawn = Vehicle.objects.create(
            code="MATCH3",
            fleet_code="1003",
            reg="AB12CDG",
            operator=self.operator,
            dvla_tax_status="SORN",
            withdrawn=True,
        )
        excluded_preserved = Vehicle.objects.create(
            code="MATCH4",
            fleet_code="1004",
            reg="AB12CDH",
            operator=self.operator,
            dvla_tax_status="SORN",
            preserved=True,
        )

        response = self.client.get("/vehicles/sorn")

        self.assertContains(response, "SORN vehicles")
        self.assertContains(response, "MATCH1")
        self.assertNotContains(response, "MATCH2")
        self.assertNotContains(response, "MATCH3")
        self.assertNotContains(response, "MATCH4")

    def test_sorn_vehicles_page_can_include_vor_and_filter_trainer(self):
        trainer_vehicle = Vehicle.objects.create(
            code="TRAIN1",
            fleet_code="2001",
            reg="AB12CDJ",
            operator=self.operator,
            dvla_tax_status="SORN",
            trainer_vehicle=True,
        )
        vor_vehicle = Vehicle.objects.create(
            code="VOR1",
            fleet_code="2002",
            reg="AB12CDK",
            operator=self.operator,
            dvla_tax_status="SORN",
            vor=True,
        )

        response = self.client.get(
            "/vehicles/sorn",
            {"include_vor": "on", "trainer_only": "on"},
        )

        self.assertContains(response, "TRAIN1")
        self.assertNotContains(response, "VOR1")

    @override_settings(
        DVLA_VEHICLE_ENQUIRY_API_KEY="test-key",
        DVLA_VEHICLE_ENQUIRY_URL="https://example.test/dvla",
        DVLA_VEHICLE_ENQUIRY_USER_AGENT="betterfleet-tests/1.0",
    )
    @patch("vehicles.tasks.requests.post")
    def test_refresh_dvla_tax_statuses_updates_non_vor_registered_vehicles(self, mock_post):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "taxStatus": "SORN",
            "motStatus": "Valid",
            "euroStatus": "EURO 6 AD",
        }
        mock_post.return_value = mock_response

        non_vor_without_reg = Vehicle.objects.create(
            code="NOREG",
            operator=self.operator,
        )
        already_vor = Vehicle.objects.create(
            code="VORBUS",
            reg="AB12CDE",
            operator=self.operator,
            vor=True,
        )

        refresh_dvla_tax_statuses()

        self.vehicle.refresh_from_db()
        non_vor_without_reg.refresh_from_db()
        already_vor.refresh_from_db()

        self.assertEqual(self.vehicle.dvla_tax_status, "SORN")
        self.assertEqual(self.vehicle.dvla_mot_status, "Valid")
        self.assertEqual(self.vehicle.dvla_euro_status, "EURO 6 AD")
        self.assertIsNotNone(self.vehicle.dvla_tax_status_checked_at)
        self.assertEqual(non_vor_without_reg.dvla_tax_status, "")
        self.assertEqual(non_vor_without_reg.dvla_mot_status, "")
        self.assertEqual(non_vor_without_reg.dvla_euro_status, "")
        self.assertEqual(already_vor.dvla_tax_status, "")
        self.assertEqual(already_vor.dvla_mot_status, "")
        self.assertEqual(already_vor.dvla_euro_status, "")
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(
            mock_post.call_args.kwargs["json"], {"registrationNumber": self.vehicle.reg}
        )

    def test_vehicle_reviews_render_on_vehicle_and_profile_pages(self):
        reviewer = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com",
            password="tram-lines-and-tea",
        )
        review = VehicleReview.objects.create(
            vehicle=self.vehicle,
            user=reviewer,
            rating=4,
            message="Smooth ride and very clean.",
        )

        response = self.client.get(self.vehicle.get_absolute_url())
        self.assertContains(response, "4.0 average from 1 review")
        self.assertContains(response, "Smooth ride and very clean.")
        review_date = timezone.localdate(review.updated_at)
        self.assertContains(response, f"{review_date.day} {review_date:%B %Y}")

        response = self.client.get(reviewer.get_absolute_url())
        self.assertContains(response, "Vehicle reviews")
        self.assertContains(response, "Smooth ride and very clean.")

    def test_logged_in_user_can_submit_vehicle_review(self):
        reviewer = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com",
            password="tram-lines-and-tea",
        )
        self.client.force_login(reviewer)

        response = self.client.post(
            self.vehicle.get_absolute_url(),
            {"rating": "5", "message": "Excellent vehicle."},
        )

        self.assertEqual(response.status_code, 200)
        review = VehicleReview.objects.get(vehicle=self.vehicle, user=reviewer)
        self.assertEqual(review.rating, Decimal("5"))
        self.assertEqual(review.message, "Excellent vehicle.")

    def test_logged_in_user_can_leave_multiple_reviews_for_one_vehicle(self):
        reviewer = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com",
            password="tram-lines-and-tea",
        )
        self.client.force_login(reviewer)

        self.client.post(
            self.vehicle.get_absolute_url(),
            {"rating": "4.5", "message": "First trip."},
        )
        self.client.post(
            self.vehicle.get_absolute_url(),
            {"rating": "3.5", "message": "Second trip."},
        )

        self.assertEqual(
            VehicleReview.objects.filter(vehicle=self.vehicle, user=reviewer).count(), 2
        )

    def test_operator_fleet_applies_vor_row_class(self):
        self.vehicle.vor = True
        self.vehicle.save(update_fields=["vor"])

        response = self.client.get("/operators/fareham-buses/vehicles")

        self.assertContains(response, 'class="fleet-row--vor"')

    def test_operator_fleet_applies_awaiting_delivery_row_class(self):
        self.vehicle.awaiting_delivery = True
        self.vehicle.save(update_fields=["awaiting_delivery"])

        response = self.client.get("/operators/fareham-buses/vehicles")

        self.assertContains(response, 'class="fleet-row--awaiting-delivery"')

    def test_operator_fleet_applies_demonstrator_row_class(self):
        self.vehicle.demonstrator = True
        self.vehicle.save(update_fields=["demonstrator"])

        response = self.client.get("/operators/fareham-buses/vehicles")

        self.assertContains(response, 'class="fleet-row--demonstrator"')

    def test_operator_fleet_combines_preserved_with_status_class(self):
        self.vehicle.vor = True
        self.vehicle.preserved = True
        self.vehicle.save(update_fields=["vor", "preserved"])

        response = self.client.get("/operators/fareham-buses/vehicles")

        self.assertContains(response, 'class="fleet-row--vor fleet-row--preserved"')

    def test_operator_fleet_links_train_fleet_code_to_flickr(self):
        train_type = VehicleType.objects.create(name="Class 195", style="train")
        self.vehicle.vehicle_type = train_type
        self.vehicle.save(update_fields=["vehicle_type"])

        response = self.client.get("/operators/fareham-buses/vehicles")

        self.assertContains(
            response,
            'href="https://www.flickr.com/search/?text=47573&amp;sort=date-taken-desc"',
            html=False,
        )

    def test_operator_fleet_renders_empty_state_when_operator_has_no_vehicles(self):
        empty_operator = Operator.objects.create(
            noc="NONE",
            name="No Fleet Buses",
            slug="no-fleet-buses",
        )

        response = self.client.get(empty_operator.get_vehicles_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "No vehicles are currently available for this operator."
        )

    def test_vehicles_index_uses_canonical_operator_fleet_urls(self):
        response = self.client.get("/vehicles")

        self.assertContains(response, self.operator.get_vehicles_url())
        self.assertNotContains(response, "/vehicles/vehicles")

    def test_withdraw_stagecoach_region_vehicles_only_withdraws_non_garage_matches(self):
        garage = Garage.objects.create(code="ALD", name="Aldershot")
        stagecoach_region = Operator.objects.create(
            noc="SCCD",
            name="Stagecoach South",
            slug="stagecoach-south",
        )
        stagecoach_garage = Operator.objects.create(
            noc="SCALD",
            name="Stagecoach Aldershot",
            slug="stagecoach-aldershot",
        )
        region_vehicle = Vehicle.objects.create(
            code="R1",
            fleet_code="R1",
            operator=stagecoach_region,
            garage=garage,
        )
        garage_vehicle = Vehicle.objects.create(
            code="G1",
            fleet_code="G1",
            operator=stagecoach_garage,
            garage=garage,
        )

        call_command("withdraw_stagecoach_region_vehicles", "--apply")

        region_vehicle.refresh_from_db()
        garage_vehicle.refresh_from_db()
        self.assertTrue(region_vehicle.withdrawn)
        self.assertFalse(garage_vehicle.withdrawn)

    def test_apply_revision_locks_feature_8_for_fleet_support(self):
        revision, features = get_revision(
            self.vehicle,
            {"fleet_support_vehicle": True, "summary": "flag as support"},
        )
        revision.save()

        apply_revision(revision, features)

        self.vehicle.refresh_from_db()
        self.assertTrue(self.vehicle.fleet_support_vehicle)
        self.assertTrue(self.vehicle.features.filter(id=8).exists())

    def test_edit_form_syncs_fleet_support_feature_to_status(self):
        data = QueryDict("", mutable=True)
        data.update(
            {
                "summary": "sync flags",
                "reg": self.vehicle.reg,
                "fleet_number": self.vehicle.fleet_code,
            }
        )
        data.setlist("features", ["8"])

        form = EditVehicleForm(
            data,
            user=self._create_user(),
            vehicle=self.vehicle,
            sibling_vehicles=(),
        )

        self.assertEqual(form.data["fleet_support_vehicle"], "on")
        self.assertIn("8", form.data.getlist("features"))

    def test_edit_form_syncs_fleet_support_status_to_feature(self):
        data = QueryDict("", mutable=True)
        data.update(
            {
                "summary": "sync flags",
                "reg": self.vehicle.reg,
                "fleet_number": self.vehicle.fleet_code,
                "fleet_support_vehicle": "on",
            }
        )

        form = EditVehicleForm(
            data,
            user=self._create_user(),
            vehicle=self.vehicle,
            sibling_vehicles=(),
        )

        self.assertIn("8", form.data.getlist("features"))

    def test_edit_form_initializes_standard_and_accessibility_features_separately(self):
        usb = VehicleFeature.objects.create(name="USB-A")
        ramp = VehicleFeature.objects.create(
            name="Wheelchair ramp",
            category=VehicleFeature.Category.ACCESSIBILITY,
        )
        self.vehicle.features.add(usb, ramp)

        form = EditVehicleForm(
            None,
            user=self._create_user(),
            vehicle=self.vehicle,
            sibling_vehicles=(),
        )

        self.assertQuerySetEqual(
            form.fields["features"].initial.order_by("id"),
            [usb],
            transform=lambda feature: feature,
        )
        self.assertQuerySetEqual(
            form.fields["accessibility_features"].initial.order_by("id"),
            [ramp],
            transform=lambda feature: feature,
        )

    def test_trusted_user_can_edit_historical_fleet_vehicle(self):
        """Test that trusted users can edit vehicles in historical fleets"""
        # Create a historical fleet vehicle
        historical_vehicle = Vehicle.objects.create(
            code="H2005",
            fleet_code="2005",
            reg="SK63KMU",
            operator=self.operator,
            historical_fleet=self.operator,
            historical_fleet_year=2005,
            withdrawn=True,  # Historical fleet vehicles are withdrawn
        )
        
        # Create a trusted user
        trusted_user = self._create_user()
        trusted_user.trusted = True
        trusted_user.save()
        
        # Create a regular (non-trusted) user
        regular_user = self._create_user()
        
        # Test that trusted user can access the edit page
        self.client.force_login(trusted_user)
        response = self.client.get(f"/vehicles/{historical_vehicle.id}/edit")
        self.assertEqual(response.status_code, 200)
        
        # Test that regular user cannot access the edit page
        self.client.force_login(regular_user)
        response = self.client.get(f"/vehicles/{historical_vehicle.id}/edit")
        self.assertEqual(response.status_code, 403)

    def test_accessibility_only_revision_keeps_existing_standard_features(self):
        usb = VehicleFeature.objects.create(name="USB-A")
        next_stop = VehicleFeature.objects.create(name="Next Stop Announcements")
        ramp = VehicleFeature.objects.create(
            name="Wheelchair ramp",
            category=VehicleFeature.Category.ACCESSIBILITY,
        )
        self.vehicle.features.add(usb, next_stop)

        revision, features = get_revision(
            self.vehicle,
            {
                "accessibility_features": [ramp],
                "summary": "add accessibility feature only",
            },
        )
        revision.save()

        apply_revision(revision, features)

        self.vehicle.refresh_from_db()
        self.assertCountEqual(
            self.vehicle.features.order_by("id").values_list("name", flat=True),
            ["USB-A", "Next Stop Announcements", "Wheelchair ramp"],
        )

    def _create_user(self):
        from accounts.models import User

        return User.objects.create_user(
            username="vehicle-editor",
            password="password",
        )
