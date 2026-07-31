from django.contrib.gis.geos import Point
from django.test import TestCase

from busstops.models import Depot, Operator, OperatorGroup, Organisation, Region
from busstops.utils import serialize_depot_map_points


class OrganisationDepotThemeTests(TestCase):
    def test_page_shell_includes_theme_switcher(self):
        response = self.client.get("/")
        self.assertContains(response, 'id="site-theme-select"')
        self.assertContains(response, '<option value="solent-blue">Solent Blue</option>', html=True)

    def test_organisation_page_shows_fleet_and_depot_tabs(self):
        organisation = Organisation.objects.create(name="Tab Org", slug="tab-org")

        response = self.client.get("/organisations/tab-org")

        self.assertContains(response, "Fleet (")
        self.assertContains(response, "Depot map (")
        self.assertContains(response, ">Map<")

    def test_organisation_page_aggregates_operator_depots(self):
        region = Region.objects.create(id="EA", name="East Anglia")
        organisation = Organisation.objects.create(name="Depot Org", slug="depot-org")
        group = OperatorGroup.objects.create(
            name="Depot Group",
            slug="depot-group",
            organisation=organisation,
        )
        grouped_operator = Operator.objects.create(
            region=region,
            name="Depot Operator",
            noc="DOP2",
            slug="depot-operator",
            group=group,
        )
        direct_operator = Operator.objects.create(
            region=region,
            organisation=organisation,
            name="Direct Operator",
            noc="DOP3",
            slug="direct-operator",
        )
        Depot.objects.create(
            operator=grouped_operator,
            name="Norwich Central",
            location=Point(1.3, 52.6),
        )
        Depot.objects.create(
            operator=direct_operator,
            name="Ipswich Depot",
            location=Point(1.4, 52.0),
        )

        response = self.client.get("/organisations/depot-org?tab=depots")

        self.assertContains(response, "Norwich Central")
        self.assertContains(response, "Ipswich Depot")
        self.assertContains(response, "depot-map-root")
        self.assertContains(response, "Depot Operator")
        self.assertContains(response, "Direct Operator")

    def test_organisation_map_url_renders(self):
        region = Region.objects.create(id="NW", name="North West")
        organisation = Organisation.objects.create(name="Live Org", slug="live-org")
        grouped = OperatorGroup.objects.create(name="Group One", slug="group-one", organisation=organisation)
        Operator.objects.create(region=region, name="Alpha", noc="ALPH", slug="alpha", group=grouped)
        Operator.objects.create(region=region, name="Bravo", noc="BRAV", slug="bravo", organisation=organisation)

        response = self.client.get("/organisations/live-org/map")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'OPERATOR_ID="ALPH,BRAV"')

    def test_depot_map_points_deduplicate_shared_locations(self):
        points = serialize_depot_map_points(
            [
                {
                    "name": "Central Depot",
                    "address": "1 Depot Road",
                    "notes": "",
                    "coordinates": [1.3, 52.6],
                    "operator_name": "Alpha Travel",
                    "operator_url": "/operators/alpha",
                    "group_name": "Group One",
                    "group_url": "/groups/group-one/vehicles",
                },
                {
                    "name": "Central Depot",
                    "address": "1 Depot Road",
                    "notes": "",
                    "coordinates": [1.3, 52.6],
                    "operator_name": "Bravo Buses",
                    "operator_url": "/operators/bravo",
                    "group_name": "Group One",
                    "group_url": "/groups/group-one/vehicles",
                },
            ]
        )

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["operator_name"], "Alpha Travel, Bravo Buses")
        self.assertEqual(points[0]["operator_url"], "")
