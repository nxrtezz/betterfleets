import datetime

from django.test import TestCase
from django.utils import timezone

from busstops.models import HomepageNotice, Operator, Organisation
from vehicles.models import Vehicle


class HomepageTests(TestCase):
    def test_homepage_includes_seo_metadata(self):
        response = self.client.get("/")

        self.assertContains(response, "<title>Better Fleets - UK Bus Fleet Database</title>", html=True)
        self.assertContains(
            response,
            '<link rel="canonical" href="https://eeveeit.uk/">',
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="description" content="Better Fleets is a UK bus fleet database with vehicle records, liveries, operators, live maps and fleet tracking tools.">',
            html=True,
        )

    def test_homepage_links_to_live_bus_map(self):
        response = self.client.get("/")

        self.assertContains(response, 'href="/map"')
        self.assertContains(response, "Live bus map")

    def test_homepage_lists_organisations(self):
        Organisation.objects.create(
            name="Example Transport Group",
            slug="example-transport-group",
            short_name="ETG",
            slogan="Regional operator group",
        )

        response = self.client.get("/")

        self.assertContains(response, "Organisations")
        self.assertContains(response, "ETG")
        self.assertContains(response, "Regional operator group")

    def test_homepage_shows_only_active_current_notices(self):
        today = timezone.localdate()
        HomepageNotice.objects.create(
            title="Current notice",
            message="Visible now",
            from_date=today - datetime.timedelta(days=1),
            to_date=today + datetime.timedelta(days=1),
            is_active=True,
        )
        HomepageNotice.objects.create(
            title="Future notice",
            message="Not yet",
            from_date=today + datetime.timedelta(days=2),
            is_active=True,
        )
        HomepageNotice.objects.create(
            title="Inactive notice",
            message="Hidden",
            is_active=False,
        )

        response = self.client.get("/")

        self.assertContains(response, "Current notice")
        self.assertContains(response, "Visible now")
        self.assertNotContains(response, "Future notice")
        self.assertNotContains(response, "Inactive notice")

    def test_recently_viewed_operator_and_vehicle_appear_on_homepage(self):
        operator = Operator.objects.create(noc="HOME", name="Home Operator", slug="home-operator")
        vehicle = Vehicle.objects.create(operator=operator, code="101", reg="AB12CDE")

        self.client.get(operator.get_absolute_url())
        self.client.get(vehicle.get_absolute_url())
        response = self.client.get("/")

        self.assertContains(response, "Recently Viewed")
        self.assertContains(response, "Home Operator")
        self.assertContains(response, "AB12 CDE")

    def test_robots_txt_allows_crawling_and_mentions_sitemap(self):
        response = self.client.get("/robots.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertContains(response, "Allow: /")
        self.assertContains(response, "Sitemap: https://eeveeit.uk/sitemap.xml")

    def test_sitemap_xml_lists_homepage_with_xml_content_type(self):
        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml")
        self.assertContains(response, "https://eeveeit.uk/")
        self.assertContains(response, "https://eeveeit.uk/fleet/")
        self.assertContains(response, "https://eeveeit.uk/register/")
        self.assertContains(response, "https://eeveeit.uk/contact/")
        self.assertContains(response, "https://eeveeit.uk/data-sources/")

