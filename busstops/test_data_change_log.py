from django.test import TestCase
from django.contrib.gis.geos import Point

from bustimes.models import Garage
from vehicles.models import Vehicle

from .bustimes_sync import apply_sync_fields
from .data_changes import apply_pending_change, reject_pending_change
from .models import BustimesSyncState, DataChangeLog, Operator, StopFeature, StopPoint


class DataChangeLogTests(TestCase):
    def test_sync_logs_applied_change(self):
        garage = Garage.objects.create(code="OLD", name="Old")

        result = apply_sync_fields(
            instance=garage,
            object_type="garage",
            external_id="garage-1",
            values={"name": "New"},
            payload={"id": "garage-1", "name": "New"},
        )

        garage.refresh_from_db()
        self.assertTrue(result.updated)
        self.assertEqual(garage.name, "New")
        log = DataChangeLog.objects.get()
        self.assertEqual(log.status, DataChangeLog.STATUS_APPLIED)
        self.assertEqual(log.changes["name"]["from"], "Old")
        self.assertEqual(log.changes["name"]["to"], "New")

    def test_sync_queues_manual_conflict_until_approval(self):
        garage = Garage.objects.create(code="GAR", name="Manual")
        BustimesSyncState.objects.create(
            object_type="garage",
            external_id="garage-2",
            local_model="bustimes.garage",
            local_pk=str(garage.pk),
            last_fields={"name": "Imported old"},
        )

        result = apply_sync_fields(
            instance=garage,
            object_type="garage",
            external_id="garage-2",
            values={"name": "Imported new"},
            payload={"id": "garage-2", "name": "Imported new"},
        )

        garage.refresh_from_db()
        self.assertEqual(garage.name, "Manual")
        self.assertEqual(result.skipped_fields, ("name",))

        log = DataChangeLog.objects.get(status=DataChangeLog.STATUS_PENDING)
        self.assertEqual(log.changes["name"]["from"], "Manual")
        self.assertEqual(log.changes["name"]["to"], "Imported new")

        apply_pending_change(log)
        garage.refresh_from_db()
        self.assertEqual(garage.name, "Imported new")

    def test_reject_pending_change_leaves_manual_value(self):
        garage = Garage.objects.create(code="GAR", name="Manual")
        log = DataChangeLog.objects.create(
            source="test",
            target_model="bustimes.garage",
            target_pk=str(garage.pk),
            target_repr=str(garage),
            operation="update",
            changes={"name": {"from": "Manual", "to": "Imported"}},
            status=DataChangeLog.STATUS_PENDING,
        )

        reject_pending_change(log, reason="keep manual value")

        garage.refresh_from_db()
        log.refresh_from_db()
        self.assertEqual(garage.name, "Manual")
        self.assertEqual(log.status, DataChangeLog.STATUS_REJECTED)
        self.assertEqual(log.reason, "keep manual value")

    def test_sync_logs_geometry_conflicts_as_wkt(self):
        stop = StopPoint.objects.create(
            atco_code="490000000A",
            common_name="Manual stop",
            active=True,
            latlong=Point(-0.1, 51.5),
        )
        BustimesSyncState.objects.create(
            object_type="stop",
            external_id=stop.atco_code,
            local_model="busstops.stoppoint",
            local_pk=str(stop.pk),
            last_fields={"latlong": "POINT (-0.11 51.49)"},
        )

        result = apply_sync_fields(
            instance=stop,
            object_type="stop",
            external_id=stop.atco_code,
            values={"latlong": Point(-0.12, 51.48)},
            payload={"id": stop.atco_code},
        )

        self.assertEqual(result.skipped_fields, ("latlong",))
        log = DataChangeLog.objects.get(status=DataChangeLog.STATUS_PENDING)
        self.assertEqual(log.changes["latlong"]["from"], "POINT (-0.1 51.5)")
        self.assertEqual(log.changes["latlong"]["to"], "POINT (-0.12 51.48)")

    def test_sync_logs_applied_geometry_changes_as_wkt(self):
        stop = StopPoint.objects.create(
            atco_code="490000000B",
            common_name="Existing stop",
            active=True,
            latlong=Point(-0.1, 51.5),
        )

        result = apply_sync_fields(
            instance=stop,
            object_type="stop",
            external_id=stop.atco_code,
            values={"latlong": Point(-0.12, 51.48)},
            payload={"id": stop.atco_code},
        )

        self.assertTrue(result.updated)
        log = DataChangeLog.objects.get(status=DataChangeLog.STATUS_APPLIED)
        self.assertEqual(log.changes["latlong"]["from"], "POINT (-0.1 51.5)")
        self.assertEqual(log.changes["latlong"]["to"], "POINT (-0.12 51.48)")

    def test_apply_pending_create_creates_vehicle(self):
        operator = Operator.objects.create(noc="TEST", name="Test Operator")
        log = DataChangeLog.objects.create(
            source="vehicle_request",
            target_model="vehicles.vehicle",
            target_pk="create:TEST:1234",
            target_repr="Test Operator 1234",
            operation="create",
            changes={
                "code": {"from": "", "to": "1234"},
                "operator": {"from": "", "to": "TEST"},
                "reg": {"from": "", "to": "YX24ABC"},
            },
            payload={
                "fields": {
                    "code": "1234",
                    "operator": "TEST",
                    "reg": "YX24ABC",
                }
            },
            status=DataChangeLog.STATUS_PENDING,
        )

        apply_pending_change(log)

        vehicle = Vehicle.objects.get(operator=operator, code="1234")
        log.refresh_from_db()
        self.assertEqual(vehicle.reg, "YX24ABC")
        self.assertEqual(log.status, DataChangeLog.STATUS_APPLIED)
        self.assertEqual(log.target_pk, str(vehicle.pk))

    def test_apply_pending_update_sets_many_to_many_fields(self):
        stop = StopPoint.objects.create(
            atco_code="490000000C",
            common_name="Feature stop",
            active=True,
        )
        shelter = StopFeature.objects.create(name="Shelter")
        ramp = StopFeature.objects.create(
            name="Step-free access",
            category=StopFeature.Category.ACCESSIBILITY,
        )
        log = DataChangeLog.objects.create(
            source="stop_request",
            target_model="busstops.stoppoint",
            target_pk=str(stop.pk),
            target_repr=stop.common_name,
            operation="update",
            changes={
                "features": {
                    "from": "",
                    "to": "Shelter, Step-free access",
                }
            },
            payload={"many_to_many": {"features": [shelter.pk, ramp.pk]}},
            status=DataChangeLog.STATUS_PENDING,
        )

        apply_pending_change(log)

        stop.refresh_from_db()
        self.assertEqual(
            list(stop.features.order_by("id").values_list("name", flat=True)),
            ["Shelter", "Step-free access"],
        )
