from django.contrib.gis.geos import Point
from django.test import TestCase

from busstops.models import Depot, Operator, OperatorGroup, Organisation, Region
from vehicles.models import Vehicle


class GroupDepotAggregationTests(TestCase):
    def test_group_page_uses_operator_owned_depots(self):
        region = Region.objects.create(id="EA", name="East Anglia")
        organisation = Organisation.objects.create(name="Depot Org", slug="depot-org")
        group = OperatorGroup.objects.create(
            name="Depot Group",
            slug="depot-group",
            organisation=organisation,
        )
        operator = Operator.objects.create(
            region=region,
            name="Depot Operator",
            noc="DOPT",
            slug="depot-operator",
            group=group,
        )
        Vehicle.objects.create(operator=operator, code="1")
        Depot.objects.create(
            operator=operator,
            name="Norwich Central",
            location=Point(1.3, 52.6),
        )

        response = self.client.get("/groups/depot-group/vehicles?tab=depots")

        self.assertContains(response, "Norwich Central")
        self.assertContains(response, "depot-map-root")

    def test_group_map_url_renders(self):
        region = Region.objects.create(id="EM", name="East Midlands")
        organisation = Organisation.objects.create(name="Live Org", slug="live-org")
        group = OperatorGroup.objects.create(name="Live Group", slug="live-group", organisation=organisation)
        operator = Operator.objects.create(
            region=region,
            name="Live Operator",
            noc="LIVE",
            slug="live-operator",
            group=group,
        )
        Vehicle.objects.create(operator=operator, code="2")

        response = self.client.get("/groups/live-group/map")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'OPERATOR_ID="LIVE"')
