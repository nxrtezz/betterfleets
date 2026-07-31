from django.core.management import call_command
from django.test import TestCase

from busstops.models import Operator, OperatorGroup, Organisation, Region
from bustimes.models import Garage
from vehicles.models import Vehicle


class AssignStagecoachGarageOperatorsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(id="SE", name="South East")

    def test_dry_run_does_not_write_changes(self):
        source_operator = Operator.objects.create(
            noc="SCSO",
            name="Stagecoach South",
            slug="stagecoach-south",
            region=self.region,
        )
        garage = Garage.objects.create(
            operator=source_operator,
            code="POR",
            name="PORTSMOUTH",
            region=self.region,
        )
        vehicle = Vehicle.objects.create(
            code="10001",
            fleet_number=10001,
            operator=source_operator,
            garage=garage,
        )

        call_command("assign_stagecoach_garage_operators")

        vehicle.refresh_from_db()
        source_operator.refresh_from_db()
        garage.refresh_from_db()

        self.assertEqual(vehicle.operator_id, source_operator.pk)
        self.assertFalse(Organisation.objects.filter(name="Stagecoach").exists())
        self.assertIsNone(source_operator.group_id)
        self.assertIsNone(source_operator.organisation_id)
        self.assertEqual(Operator.objects.count(), 1)
        self.assertEqual(garage.operator_id, source_operator.pk)

    def test_apply_creates_group_organisation_and_garage_operator(self):
        source_operator = Operator.objects.create(
            noc="SCSO",
            name="Stagecoach South",
            slug="stagecoach-south",
            region=self.region,
        )
        garage = Garage.objects.create(
            operator=source_operator,
            code="POR",
            name="PORTSMOUTH",
            region=self.region,
        )
        vehicle = Vehicle.objects.create(
            code="10002",
            fleet_number=10002,
            operator=source_operator,
            garage=garage,
        )

        call_command("assign_stagecoach_garage_operators", apply=True)

        vehicle.refresh_from_db()
        source_operator.refresh_from_db()
        garage.refresh_from_db()

        organisation = Organisation.objects.get(name="Stagecoach")
        group = OperatorGroup.objects.get(name="Stagecoach South")
        target_operator = Operator.objects.get(name="Stagecoach Portsmouth")

        self.assertEqual(source_operator.organisation_id, organisation.pk)
        self.assertEqual(source_operator.group_id, group.pk)
        self.assertEqual(group.organisation_id, organisation.pk)

        self.assertEqual(target_operator.organisation_id, organisation.pk)
        self.assertEqual(target_operator.group_id, group.pk)
        self.assertEqual(target_operator.region_id, self.region.pk)
        self.assertTrue(target_operator.is_manual)
        self.assertEqual(target_operator.external_id, "stagecoach-garage:portsmouth")

        self.assertEqual(vehicle.operator_id, target_operator.pk)
        self.assertEqual(garage.operator_id, target_operator.pk)

    def test_apply_reuses_existing_garage_operator_and_stagecoach_org(self):
        organisation = Organisation.objects.create(name="Stagecoach", slug="stagecoach")
        group = OperatorGroup.objects.create(
            name="Stagecoach South",
            slug="stagecoach-south",
            organisation=organisation,
        )
        source_operator = Operator.objects.create(
            noc="SCSO",
            name="Stagecoach South",
            slug="stagecoach-south-operator",
            region=self.region,
            group=group,
            organisation=organisation,
        )
        target_operator = Operator.objects.create(
            noc="SCPORTSM",
            name="Stagecoach Portsmouth",
            slug="stagecoach-portsmouth",
            region=self.region,
            group=group,
            organisation=organisation,
            external_id="stagecoach-garage:portsmouth",
            is_manual=True,
        )
        garage = Garage.objects.create(
            operator=source_operator,
            code="POR",
            name="Portsmouth",
            region=self.region,
        )
        vehicle = Vehicle.objects.create(
            code="10003",
            fleet_number=10003,
            operator=source_operator,
            garage=garage,
        )

        call_command("assign_stagecoach_garage_operators", apply=True)

        vehicle.refresh_from_db()
        garage.refresh_from_db()

        self.assertEqual(Organisation.objects.filter(name="Stagecoach").count(), 1)
        self.assertEqual(OperatorGroup.objects.filter(name="Stagecoach South").count(), 1)
        self.assertEqual(Operator.objects.filter(name="Stagecoach Portsmouth").count(), 1)
        self.assertEqual(vehicle.operator_id, target_operator.pk)
        self.assertEqual(garage.operator_id, target_operator.pk)

    def test_apply_moves_existing_stagecoach_operator_into_stagecoach_organisation(self):
        other_org = Organisation.objects.create(name="Legacy Parent", slug="legacy-parent")
        source_operator = Operator.objects.create(
            noc="SCSO",
            name="Stagecoach South",
            slug="stagecoach-south",
            region=self.region,
            organisation=other_org,
        )
        garage = Garage.objects.create(
            operator=source_operator,
            code="POR",
            name="Portsmouth",
            region=self.region,
        )
        vehicle = Vehicle.objects.create(
            code="10004",
            fleet_number=10004,
            operator=source_operator,
            garage=garage,
        )

        call_command("assign_stagecoach_garage_operators", apply=True)

        vehicle.refresh_from_db()
        source_operator.refresh_from_db()

        organisation = Organisation.objects.get(name="Stagecoach")
        self.assertEqual(source_operator.organisation_id, organisation.pk)
        self.assertEqual(vehicle.operator.name, "Stagecoach Portsmouth")

    def test_apply_can_be_scoped_to_specific_nocs(self):
        south_operator = Operator.objects.create(
            noc="SCSO",
            name="Stagecoach South",
            slug="stagecoach-south",
            region=self.region,
        )
        midlands_operator = Operator.objects.create(
            noc="SCCM",
            name="Stagecoach Midlands",
            slug="stagecoach-midlands",
            region=self.region,
        )
        south_garage = Garage.objects.create(
            operator=south_operator,
            code="POR",
            name="Portsmouth",
            region=self.region,
        )
        midlands_garage = Garage.objects.create(
            operator=midlands_operator,
            code="NUN",
            name="Nuneaton",
            region=self.region,
        )
        south_vehicle = Vehicle.objects.create(
            code="10005",
            fleet_number=10005,
            operator=south_operator,
            garage=south_garage,
        )
        midlands_vehicle = Vehicle.objects.create(
            code="20005",
            fleet_number=20005,
            operator=midlands_operator,
            garage=midlands_garage,
        )

        call_command("assign_stagecoach_garage_operators", apply=True, nocs=["SCSO"])

        south_vehicle.refresh_from_db()
        midlands_vehicle.refresh_from_db()
        south_garage.refresh_from_db()
        midlands_garage.refresh_from_db()

        self.assertEqual(south_vehicle.operator.name, "Stagecoach Portsmouth")
        self.assertEqual(south_garage.operator.name, "Stagecoach Portsmouth")
        self.assertEqual(midlands_vehicle.operator_id, midlands_operator.pk)
        self.assertEqual(midlands_garage.operator_id, midlands_operator.pk)
        self.assertFalse(Operator.objects.filter(name="Stagecoach Nuneaton").exists())

    def test_apply_noc_scope_does_not_require_stagecoach_in_source_operator_name(self):
        source_operator = Operator.objects.create(
            noc="SCSO",
            name="South Coast Ops",
            slug="south-coast-ops",
            region=self.region,
        )
        target_operator = Operator.objects.create(
            noc="SCPORTSM",
            name="Stagecoach Portsmouth",
            slug="stagecoach-portsmouth",
            region=self.region,
            external_id="stagecoach-garage:portsmouth",
            is_manual=True,
        )
        garage = Garage.objects.create(
            operator=source_operator,
            code="POR",
            name="Portsmouth",
            region=self.region,
        )
        vehicle = Vehicle.objects.create(
            code="10006",
            fleet_number=10006,
            operator=source_operator,
            garage=garage,
        )

        call_command("assign_stagecoach_garage_operators", apply=True, nocs=["SCSO"])

        vehicle.refresh_from_db()
        garage.refresh_from_db()

        self.assertEqual(vehicle.operator_id, target_operator.pk)
        self.assertEqual(garage.operator_id, target_operator.pk)

    def test_apply_can_be_scoped_by_garage_operator_noc(self):
        garage_source_operator = Operator.objects.create(
            noc="SCSO",
            name="Stagecoach South",
            slug="stagecoach-south",
            region=self.region,
        )
        current_vehicle_operator = Operator.objects.create(
            noc="TEMP",
            name="Temporary Operator",
            slug="temporary-operator",
            region=self.region,
        )
        target_operator = Operator.objects.create(
            noc="SCPORTSM",
            name="Stagecoach Portsmouth",
            slug="stagecoach-portsmouth",
            region=self.region,
            external_id="stagecoach-garage:portsmouth",
            is_manual=True,
        )
        garage = Garage.objects.create(
            operator=garage_source_operator,
            code="POR",
            name="Portsmouth",
            region=self.region,
        )
        vehicle = Vehicle.objects.create(
            code="10007",
            fleet_number=10007,
            operator=current_vehicle_operator,
            garage=garage,
        )

        call_command(
            "assign_stagecoach_garage_operators",
            apply=True,
            garage_operator_nocs=["SCSO"],
        )

        vehicle.refresh_from_db()
        garage.refresh_from_db()

        self.assertEqual(vehicle.operator_id, target_operator.pk)
        self.assertEqual(garage.operator_id, target_operator.pk)
