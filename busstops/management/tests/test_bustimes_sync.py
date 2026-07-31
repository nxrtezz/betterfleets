from unittest.mock import Mock, patch

from django.db import IntegrityError
from django.core.management import call_command
from django.test import TestCase

from bustimes.models import Garage
from busstops.models import DataSource, Operator, Service, ServiceCode, StopPoint
from vehicles.models import Livery, Vehicle, VehicleCode


def make_response(payload):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


class BustimesSyncCommandTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = Operator.objects.create(
            noc="NATX",
            name="National Express",
            slug="national-express",
        )
        DataSource.objects.create(name="Bustimes API", url="https://bustimes.org/api/")

    def test_vehicle_sync_passes_operator_query_param(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 0,
                        "next": None,
                        "previous": None,
                        "results": [],
                    }
                ),
            ],
        ) as mocked_get:
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        self.assertEqual(mocked_get.call_count, 2)
        self.assertEqual(mocked_get.call_args_list[1].args[0], "https://bustimes.org/api/vehicles/?limit=100&operator=NATX")

    def test_service_sync_passes_operator_query_param(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "services": "https://bustimes.org/api/services/",
                    }
                ),
                make_response(
                    {
                        "count": 0,
                        "next": None,
                        "previous": None,
                        "results": [],
                    }
                ),
            ],
        ) as mocked_get:
            call_command("sync_bustimes_services", operator="NATX")

        self.assertEqual(mocked_get.call_count, 2)
        self.assertEqual(
            mocked_get.call_args_list[1].args[0],
            "https://bustimes.org/api/services/?limit=100&operator=NATX",
        )

    def test_stop_sync_passes_region_query_param(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "stops": "https://bustimes.org/api/stops/",
                    }
                ),
                make_response(
                    {
                        "count": 0,
                        "next": None,
                        "previous": None,
                        "results": [],
                    }
                ),
            ],
        ) as mocked_get:
            call_command("sync_bustimes_stops", region="L")

        self.assertEqual(mocked_get.call_count, 2)
        self.assertEqual(
            mocked_get.call_args_list[1].args[0],
            "https://bustimes.org/api/stops/?limit=100&region=L&atco_code__startswith=49",
        )

    def test_stop_sync_skips_items_from_other_regions(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "stops": "https://bustimes.org/api/stops/",
                    }
                ),
                make_response(
                    {
                        "count": 2,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "atco_code": "490001064A",
                                "common_name": "Chislehurst Station (Stop A)",
                                "region_id": "L",
                                "active": True,
                                "location": [-0.07, 51.41],
                            },
                            {
                                "atco_code": "390070956",
                                "common_name": "Halesworth, opposite Garage",
                                "region_id": "EA",
                                "active": True,
                                "location": [1.5, 52.34],
                            },
                        ],
                    }
                ),
            ],
        ):
            call_command("sync_bustimes_stops", region="L")

        self.assertTrue(StopPoint.objects.filter(atco_code="490001064A").exists())
        self.assertFalse(StopPoint.objects.filter(atco_code="390070956").exists())

    def test_stop_sync_fetches_exact_atco_code(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "stops": "https://bustimes.org/api/stops/",
                    }
                ),
                make_response(
                    {
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "atco_code": "490014051VC",
                                "common_name": "Victoria Coach Station",
                                "active": True,
                                "location": [-0.14922, 51.49267],
                            },
                        ],
                    }
                ),
            ],
        ) as mocked_get:
            call_command("sync_bustimes_stops", atco_code=["490014051VC"])

        self.assertEqual(
            mocked_get.call_args_list[1].args[0],
            "https://bustimes.org/api/stops/?atco_code=490014051VC",
        )
        self.assertTrue(StopPoint.objects.filter(atco_code="490014051VC").exists())

    def test_stop_sync_falls_back_to_exact_atco_lookup(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "stops": "https://bustimes.org/api/stops/",
                    }
                ),
                make_response(
                    {
                        "next": None,
                        "previous": None,
                        "results": [],
                    }
                ),
                make_response(
                    {
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "atco_code": "490014051VC",
                                "common_name": "Victoria Coach Station",
                                "active": True,
                                "location": [-0.14922, 51.49267],
                            },
                        ],
                    }
                ),
            ],
        ) as mocked_get:
            call_command("sync_bustimes_stops", atco_code=["490014051VC"])

        self.assertEqual(
            mocked_get.call_args_list[2].args[0],
            "https://bustimes.org/api/stops/?atco_code__iexact=490014051VC",
        )
        self.assertTrue(StopPoint.objects.filter(atco_code="490014051VC").exists())

    def test_vehicle_sync_matches_livery_by_left_css_and_name(self):
        Livery.objects.create(
            name="Wrong Match",
            colour="#111111",
            left_css="#123456",
            right_css="#123456",
            published=True,
        )
        target_livery = Livery.objects.create(
            name="Correct Match",
            colour="#222222",
            left_css="#123456",
            right_css="#123456",
            published=True,
        )

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 99,
                                "code": "1001",
                                "fleet_code": "1001",
                                "reg": "AB12CDE",
                                "operator": "NATX",
                                "livery": {
                                    "name": "Correct Match",
                                    "left": "#123456",
                                },
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        vehicle = Vehicle.objects.get(reg="AB12CDE")
        self.assertEqual(vehicle.livery_id, target_livery.pk)
        self.assertTrue(
            VehicleCode.objects.filter(
                vehicle=vehicle,
                scheme="bustimes",
                code="99",
            ).exists()
        )

    def test_vehicle_sync_imports_garage_notes_and_special_features(self):
        garage = Garage.objects.create(
            operator=self.operator,
            code="CB",
            name="Leckwith",
        )

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 1,
                                "slug": "natx-141",
                                "fleet_number": 141,
                                "fleet_code": "141",
                                "reg": "CN11KFZ",
                                "previous_reg": "KMN-205-L",
                                "vehicle_type": {
                                    "id": 36,
                                    "name": "Mercedes-Benz Citaro O530",
                                    "style": "",
                                    "fuel": "diesel",
                                    "double_decker": False,
                                    "coach": False,
                                    "electric": False,
                                },
                                "livery": {
                                    "id": 1078,
                                    "name": "Test Livery",
                                    "left": "#123456",
                                    "right": "#123456",
                                },
                                "branding": "",
                                "operator": {
                                    "id": "NATX",
                                    "slug": "national-express",
                                    "name": "National Express",
                                },
                                "garage": {
                                    "id": garage.pk,
                                    "code": "CB",
                                    "name": "Leckwith",
                                    "location": None,
                                    "address": "",
                                    "operator": None,
                                },
                                "name": "",
                                "notes": "Allocated to depot pool",
                                "withdrawn": False,
                                "special_features": ["Wi-Fi"],
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        vehicle = Vehicle.objects.get(reg="CN11KFZ")
        self.assertEqual(vehicle.garage_id, garage.pk)
        self.assertEqual(vehicle.notes, "Allocated to depot pool")
        self.assertEqual(vehicle.prev_registration, "KMN-205-L")
        self.assertEqual(vehicle.vehicle_type.name, "Mercedes-Benz Citaro O530")
        self.assertEqual(list(vehicle.features.values_list("name", flat=True)), ["Wi-Fi"])

    def test_vehicle_sync_can_limit_updates_to_garage_field(self):
        old_garage = Garage.objects.create(
            operator=self.operator,
            code="OLD",
            name="Old Depot",
        )
        new_garage = Garage.objects.create(
            operator=self.operator,
            code="PM",
            name="Portsmouth",
        )
        vehicle = Vehicle.objects.create(
            code="36256",
            fleet_code="36256",
            reg="WA11CHV",
            operator=self.operator,
            garage=old_garage,
            branding="Keep me",
            notes="Keep these notes",
        )

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 17662,
                                "slug": "scpy-36256",
                                "fleet_number": 36256,
                                "fleet_code": "36256",
                                "reg": "WA11CHV",
                                "previous_reg": "",
                                "vehicle_type": {
                                    "id": 3,
                                    "name": "ADL Enviro200",
                                    "style": "",
                                    "fuel": "diesel",
                                    "double_decker": False,
                                    "coach": False,
                                    "electric": False,
                                },
                                "livery": {
                                    "id": 3459,
                                    "name": "Stagecoach, we've got you",
                                    "left": "#1f2c54",
                                    "right": "#1f2c54",
                                },
                                "branding": "",
                                "operator": {
                                    "id": "NATX",
                                    "slug": "national-express",
                                    "name": "National Express",
                                },
                                "garage": {
                                    "id": new_garage.pk,
                                    "code": "PM",
                                    "name": "Portsmouth",
                                    "location": None,
                                    "address": "",
                                    "operator": None,
                                },
                                "name": "",
                                "notes": "",
                                "withdrawn": False,
                                "special_features": None,
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command(
                "sync_bustimes_vehicles",
                operator="NATX",
                fields=["garage"],
            )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.garage_id, new_garage.pk)
        self.assertEqual(vehicle.branding, "Keep me")
        self.assertEqual(vehicle.notes, "Keep these notes")

    def test_vehicle_sync_imports_nested_vehicle_fields(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 200,
                                "operator": "NATX",
                                "vehicle": {
                                    "code": "200",
                                    "fleet_code": "200",
                                    "reg": "AB12CDE",
                                    "name": "Nested vehicle",
                                    "branding": "Airport",
                                    "notes": "Nested notes",
                                },
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        vehicle = Vehicle.objects.get(operator=self.operator, code="200")
        self.assertEqual(vehicle.reg, "AB12CDE")
        self.assertEqual(vehicle.name, "Nested vehicle")
        self.assertEqual(vehicle.branding, "Airport")
        self.assertEqual(vehicle.notes, "Nested notes")

    def test_vehicle_sync_creates_css_livery_when_bustimes_omits_id_and_name(self):
        left_css = "linear-gradient(90deg,#ffffff 13%,#000000 13%,#000000 25%,#c0c0c0 25%,#c0c0c0 38%,#000000 38%,#000000 50%,#c0c0c0 50%,#c0c0c0 63%,#000000 63%,#000000 75%,#c0c0c0 75%,#c0c0c0 88%,#000000 88%)"
        right_css = "linear-gradient(270deg,#ffffff 13%,#000000 13%,#000000 25%,#c0c0c0 25%,#c0c0c0 38%,#000000 38%,#000000 50%,#c0c0c0 50%,#c0c0c0 63%,#000000 63%,#000000 75%,#c0c0c0 75%,#c0c0c0 88%,#000000 88%)"

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 100,
                                "code": "1002",
                                "fleet_code": "1002",
                                "reg": "BC13DEF",
                                "operator": "NATX",
                                "livery": {
                                    "id": None,
                                    "name": None,
                                    "left": left_css,
                                    "right": right_css,
                                },
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        vehicle = Vehicle.objects.get(reg="BC13DEF")
        self.assertIsNotNone(vehicle.livery_id)
        self.assertEqual(vehicle.livery.left_css, Livery.minify(left_css))
        self.assertEqual(vehicle.livery.right_css, Livery.minify(right_css))
        self.assertEqual(vehicle.livery.colour, "#ffffff")
        self.assertFalse(vehicle.livery.show_name)

    def test_vehicle_sync_merges_into_existing_operator_code_vehicle(self):
        duplicate = Vehicle.objects.create(
            code="old-code",
            fleet_code="old-code",
            reg="AB12CDE",
            operator=self.operator,
        )
        VehicleCode.objects.create(vehicle=duplicate, scheme="bustimes", code="123")

        canonical = Vehicle.objects.create(
            code="245",
            fleet_code="245",
            reg="",
            operator=self.operator,
        )

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 123,
                                "code": "245",
                                "fleet_code": "245",
                                "reg": "AB12CDE",
                                "operator": "NATX",
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        self.assertFalse(Vehicle.objects.filter(pk=duplicate.pk).exists())
        canonical.refresh_from_db()
        self.assertEqual(canonical.reg, "AB12CDE")
        self.assertTrue(
            VehicleCode.objects.filter(
                vehicle=canonical,
                scheme="bustimes",
                code="123",
            ).exists()
        )

    def test_vehicle_sync_truncates_short_vehicle_fields(self):
        long_value = "A" * 40

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 321,
                                "code": "safe-code",
                                "fleet_code": long_value,
                                "reg": long_value,
                                "prev_registration": long_value,
                                "operator": "NATX",
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        vehicle = Vehicle.objects.get(operator=self.operator, code="safe-code")
        self.assertEqual(vehicle.fleet_code, long_value[:24])
        self.assertEqual(vehicle.reg, long_value[:24])
        self.assertEqual(vehicle.prev_registration, long_value[:24])

    def test_vehicle_sync_reuses_existing_blank_code_vehicle_for_operator(self):
        vehicle = Vehicle.objects.create(
            code="",
            fleet_code="",
            reg="",
            operator=self.operator,
            name="Before",
        )

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "operator": "NATX",
                                "name": "After",
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="NATX")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.name, "After")
        self.assertEqual(Vehicle.objects.filter(operator=self.operator, code="").count(), 1)

    def test_vehicle_sync_batches_requests_by_bustimes_operator_noc(self):
        source = DataSource.objects.get(name="Bustimes API")
        self.operator.source = source
        self.operator.save(update_fields=["source"])
        second_operator = Operator.objects.create(
            noc="ABCD",
            name="Alpha Buses",
            slug="alpha-buses",
            source=source,
        )
        Operator.objects.create(
            noc="LONGER",
            name="Long Operator",
            slug="long-operator",
            source=source,
        )
        Operator.objects.create(
            noc="SCPT",
            name="Stagecoach Portsmouth",
            slug="stagecoach-portsmouth",
            source=source,
            external_id="stagecoach-garage:portsmouth",
            is_manual=True,
        )

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 0,
                        "next": None,
                        "previous": None,
                        "results": [],
                    }
                ),
                make_response(
                    {
                        "count": 0,
                        "next": None,
                        "previous": None,
                        "results": [],
                    }
                ),
            ],
        ) as mocked_get:
            call_command("sync_bustimes_vehicles")

        self.assertEqual(mocked_get.call_count, 3)
        vehicle_urls = [call.args[0] for call in mocked_get.call_args_list[1:]]
        self.assertEqual(
            vehicle_urls,
            [
                f"https://bustimes.org/api/vehicles/?limit=100&operator={second_operator.noc}",
                f"https://bustimes.org/api/vehicles/?limit=100&operator={self.operator.noc}",
            ],
        )

    def test_vehicle_sync_recovers_from_blank_code_operator_conflict(self):
        source = Vehicle.objects.create(
            code="SRC1",
            fleet_code="SRC1",
            reg="",
            operator=self.operator,
            name="Source",
        )
        target = Vehicle.objects.create(
            code="",
            fleet_code="",
            reg="",
            operator=self.operator,
            name="Target",
        )

        command = __import__(
            "busstops.management.commands.sync_bustimes_vehicles",
            fromlist=["Command"],
        ).Command()

        item = {"id": 999, "operator": "NATX", "name": "Recovered"}
        options = {
            "dry_run": False,
            "force": False,
            "operator": "NATX",
            "base_url": None,
            "limit": 100,
            "max_items": None,
            "progress": False,
            "no_progress": True,
        }

        original_apply = __import__(
            "busstops.management.commands.sync_bustimes_vehicles",
            fromlist=["apply_sync_fields"],
        ).apply_sync_fields
        calls = {"count": 0}

        def flaky_apply(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise IntegrityError("duplicate key value violates unique constraint \"vehicle_operator_and_code\"")
            return original_apply(*args, **kwargs)

        with patch(
            "busstops.management.commands.sync_bustimes_vehicles.resolve_vehicle",
            return_value=source,
        ), patch(
            "busstops.management.commands.sync_bustimes_vehicles.apply_sync_fields",
            side_effect=flaky_apply,
        ):
            created, updated, skipped = command.sync_item(item, options)

        self.assertFalse(Vehicle.objects.filter(pk=source.pk).exists())
        target.refresh_from_db()
        self.assertEqual(target.name, "Recovered")
        self.assertFalse(created)
        self.assertTrue(updated)
        self.assertEqual(skipped, 0)

    def test_vehicle_sync_does_not_move_stagecoach_garage_split_vehicle(self):
        original_operator = Operator.objects.create(
            noc="SCSO",
            name="Stagecoach South",
            slug="stagecoach-south",
        )
        split_operator = Operator.objects.create(
            noc="SCPORTS",
            name="Stagecoach Portsmouth",
            slug="stagecoach-portsmouth",
            external_id="stagecoach-garage:portsmouth",
            is_manual=True,
        )
        vehicle = Vehicle.objects.create(
            code="1005",
            fleet_code="1005",
            reg="AB12CDE",
            operator=split_operator,
        )
        VehicleCode.objects.create(vehicle=vehicle, scheme="bustimes", code="555")

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "vehicles": "https://bustimes.org/api/vehicles/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 555,
                                "code": "1005",
                                "fleet_code": "1005",
                                "reg": "AB12CDE",
                                "operator": "SCSO",
                                "name": "Updated name",
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("bustimes_sync", vehicles=True, operator="SCSO")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.operator_id, split_operator.pk)
        self.assertEqual(vehicle.name, "Updated name")

    def test_service_sync_skips_existing_operator_service_code(self):
        Service.objects.create(
            service_code="PF0000001:123",
            line_name="123",
            description="Existing BODS service",
            current=True,
            source=DataSource.objects.create(name="BODS"),
        ).operator.add(self.operator)

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "services": "https://bustimes.org/api/services/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 500,
                                "slug": "123-town-centre",
                                "service_code": "PF0000001:123",
                                "line_name": "123",
                                "description": "Bustimes duplicate",
                                "operator": ["NATX"],
                                "region_id": "NW",
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("sync_bustimes_services")

        self.assertEqual(Service.objects.filter(service_code="PF0000001:123").count(), 1)
        self.assertFalse(
            ServiceCode.objects.filter(scheme="bustimes", code="500").exists()
        )

    def test_service_sync_updates_existing_bustimes_linked_service(self):
        service = Service.objects.create(
            service_code="PF0000001:123",
            line_name="123",
            description="Before",
            current=True,
        )
        service.operator.add(self.operator)
        ServiceCode.objects.create(service=service, scheme="bustimes", code="500")

        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "services": "https://bustimes.org/api/services/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 500,
                                "slug": "123-town-centre",
                                "service_code": "PF0000001:123",
                                "line_name": "123",
                                "description": "After",
                                "operator": ["NATX"],
                                "region_id": "NW",
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("sync_bustimes_services")

        service.refresh_from_db()
        self.assertEqual(service.description, "After")
        self.assertTrue(
            ServiceCode.objects.filter(
                service=service,
                scheme="bustimes-slug",
                code="123-town-centre",
            ).exists()
        )

    def test_service_sync_creates_slug_for_new_service(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "services": "https://bustimes.org/api/services/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 501,
                                "slug": "124-town-centre",
                                "service_code": "PF0000001:124",
                                "line_name": "124",
                                "description": "Town Centre",
                                "operator": ["NATX"],
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("sync_bustimes_services")

        service = Service.objects.get(service_code="PF0000001:124")
        self.assertEqual(service.slug, "124-town-centre")

    def test_service_sync_derives_line_name_from_slug_when_missing(self):
        with patch(
            "busstops.bustimes_sync.requests.Session.get",
            side_effect=[
                make_response(
                    {
                        "services": "https://bustimes.org/api/services/",
                    }
                ),
                make_response(
                    {
                        "count": 1,
                        "next": None,
                        "previous": None,
                        "results": [
                            {
                                "id": 70882,
                                "slug": "200-bristol-gatwick-airport-south-2",
                                "service_code": "",
                                "line_name": "",
                                "description": "Bristol - Gatwick Airport (South)",
                                "operator": ["NATX"],
                            }
                        ],
                    }
                ),
            ],
        ):
            call_command("sync_bustimes_services")

        service = Service.objects.get(slug="200-bristol-gatwick-airport-south-2")
        self.assertEqual(service.line_name, "200")
        self.assertEqual(service.service_code, "200")
