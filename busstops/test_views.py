import json
from unittest.mock import Mock, patch

import time_machine
import vcr
from django.contrib.auth.models import Permission
from django.conf import settings
from django.contrib.gis.geos import Point
from django.core import mail
from django.core.management import call_command
from django.shortcuts import render
from django.test import Client, TestCase, override_settings
from datetime import date

from accounts.models import User
from bustimes.models import Route, RouteLink, StopTime, Trip

# Import fares models defensively
try:
    from fares.models import (
        DataSet,
        FareTable,
        PreassignedFareProduct,
        Price,
        SalesOfferPackage,
        Tariff,
        Ticket,
        TicketAcceptance,
    )
    FARES_AVAILABLE = True
except (ImportError, ProgrammingError):
    FARES_AVAILABLE = False

# Import disruptions models defensively
try:
    from disruptions.models import Situation
    DISRUPTIONS_AVAILABLE = True
except (ImportError, ProgrammingError):
    DISRUPTIONS_AVAILABLE = False

from .models import (
    AdminArea,
    DataSource,
    District,
    Locality,
    Manufacturer,
    ManufacturerSite,
    Organisation,
    Operator,
    OperatorGroup,
    PaymentMethod,
    PreservationGroup,
    Region,
    RouteNotice,
    Service,
    ServiceCode,
    ServicePaymentMethod,
    StopGroup,
    StopFeature,
    StopPoint,
    StopUsage,
)
from vehicles.models import Vehicle, VehicleNamePage, VehicleType, VehicleTypeGroup


class ContactTests(TestCase):
    """Tests for the contact form and view"""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username="bob", email="bob@example.com")

    def test_contact_get(self):
        response = self.client.get("/contact")
        self.assertEqual(response.status_code, 200)

        # user logged in - set initial email address value
        self.client.force_login(self.user)
        response = self.client.get("/contact")
        self.assertContains(response, ' value="bob@example.com" ')

    def test_empty_contact_post(self):
        response = self.client.post("/contact")
        self.assertFalse(response.context["form"].is_valid())

    @patch("turnstile.fields.TurnstileField.validate", return_value=True)
    def test_contact_post(self, mock_validate):
        self.client.force_login(self.user)

        response = self.client.post(
            "/contact",
            {
                "name": 'Rufus "Red" Herring',
                "email": "rufus@example.com",
                "message": "Dear John,\r\n\r\nHow are you?\r\n\r\nAll the best,\r\nRufus",
                "referrer": "https://www.yahoo.com",
            },
        )

        self.assertContains(response, "<h1>Thank you</h1>", html=True)

        message = mail.outbox[0]
        self.assertEqual(message.subject, "Dear John,")
        self.assertEqual(
            message.from_email, '"Rufus "Red" Herring" <contactform@bustimes.org>'
        )
        self.assertEqual(message.to, ["contact@bustimes.org"])
        self.assertIn("https://www.yahoo.com", message.body)
        self.assertIn(f"/accounts/users/{self.user.id}/", message.body)


class ViewsTests(TestCase):
    """Boring tests for various views"""

    @classmethod
    @time_machine.travel("2023-02-21")
    def setUpTestData(cls):
        cls.north = Region.objects.create(pk="N", name="North")
        cls.norfolk = AdminArea.objects.create(
            id=91, atco_code=91, region=cls.north, name="Norfolk"
        )
        cls.north_norfolk = District.objects.create(
            id=91, admin_area=cls.norfolk, name="North Norfolk"
        )
        cls.melton_constable = Locality.objects.create(
            id="E0048689",
            admin_area=cls.norfolk,
            name="Melton Constable",
            latlong=Point(-0.14, 51.51),
        )
        cls.inactive_stop = StopPoint.objects.create(
            pk="2900M115",
            common_name="Bus Shelter",
            active=False,
            admin_area=cls.norfolk,
            locality=cls.melton_constable,
            locality_centre=False,
            indicator="adj",
            bearing="E",
            latlong=Point(1.041894987727773, 52.85610279717982),
        )
        cls.stop = StopPoint.objects.create(
            atco_code="2900M114",
            naptan_code="NFODGJTG",
            common_name="Bus Shelter",
            active=True,
            admin_area=cls.norfolk,
            locality=cls.melton_constable,
            locality_centre=False,
            indicator="opp",
            bearing="W",
            latlong=Point(1.041894987727773, 52.85610279717982),
        )
        cls.stop.features.add(
            StopFeature.objects.create(name="Shelter"),
            StopFeature.objects.create(
                name="Step-free access",
                category=StopFeature.Category.ACCESSIBILITY,
            ),
        )
        cls.inactive_service = Service.objects.create(
            service_code="45A", line_name="45A", region=cls.north, current=False
        )
        StopUsage.objects.create(service=cls.inactive_service, stop=cls.stop, order=0)
        cls.inactive_service_with_alternative = Service.objects.create(
            service_code="45B",
            line_name="45B",
            description="Holt - Norwich",
            region=cls.north,
            current=False,
        )
        cls.service = Service.objects.create(
            service_code="ea_21-45-A-y08",
            line_name="45C",
            description="Holt - Norwich",
            region=cls.north,
        )
        source = DataSource.objects.create()
        route = Route.objects.create(
            service=cls.service, source=source, line_name="45C"
        )
        trip = Trip.objects.create(route=route, start="0", end="1")
        StopTime.objects.create(trip=trip, stop=cls.stop, arrival="2")
        StopUsage.objects.create(service=cls.service, stop=cls.stop, order=0)

        Service.objects.bulk_create(
            [
                Service(line_name=str(i), description="Sandwich - Deal", current=True)
                for i in range(1, 30)
            ]
        )

        cls.chariots = Operator.objects.create(
            noc="AINS",
            name="Ainsley's Chariots",
            vehicle_mode="airline",
            region_id="N",
            address="10 King Road\nIpswich",
            phone="0800 1111",
            email="ainsley@example.com",
            url="http://www.ouibus.com",
            twitter="dril\ncoldwarsteve",
        )
        cls.nuventure = Operator.objects.create(
            noc="VENT", name="Nu-Venture", vehicle_mode="bus", region_id="N"
        )
        cls.organisation = Organisation.objects.create(
            name="Ainsley Transport Group",
            slug="ainsley-transport-group",
            short_name="ATG",
            legal_name="Ainsley Transport Group plc",
            slogan="Moving people across the region",
            description="Parent company for several local transport businesses.",
            website="https://example.com/atg",
            email="hello@example.com",
            phone="0800 000 000",
            social_x="https://x.example/atg",
            social_linkedin="https://linkedin.example/atg",
            social_youtube="https://youtube.example/atg",
            header_background="#10243f",
            header_foreground="#f8fafc",
            accent_colour="#f97316",
            button_background="#ffedd5",
            button_foreground="#9a3412",
            custom_css=".organisation-profile__banner{min-height:9rem;}",
        )
        cls.division = OperatorGroup.objects.create(
            name="Ainsley East",
            slug="ainsley-east",
            organisation=cls.organisation,
        )
        cls.manufacturer = Manufacturer.objects.create(
            name="Alexander Dennis",
            slug="alexander-dennis",
            short_name="ADL",
            slogan="Engineering the next generation of buses",
            description="Known for double deckers and zero-emission platforms.",
            website="https://example.com/adl",
            social_x="https://x.example/adl",
        )
        ManufacturerSite.objects.create(
            manufacturer=cls.manufacturer,
            name="Falkirk",
            site_type=ManufacturerSite.SiteType.FACTORY,
            address="Camelon Road, Falkirk",
            location=Point(-3.804, 56.001),
        )
        ManufacturerSite.objects.create(
            manufacturer=cls.manufacturer,
            name="Larbert HQ",
            site_type=ManufacturerSite.SiteType.HEAD_OFFICE,
            address="Larbert",
        )
        cls.enviro200 = VehicleType.objects.create(
            name="Enviro200",
            manufacturer=cls.manufacturer,
            style="",
            fuel="diesel",
            active_production=False,
        )
        cls.enviro200_group = VehicleTypeGroup.objects.create(
            manufacturer=cls.manufacturer,
            name="Enviro200",
        )
        cls.enviro200.vehicle_group = cls.enviro200_group
        cls.enviro200.save(update_fields=["vehicle_group"])
        cls.enviro200mmc = VehicleType.objects.create(
            name="Enviro200MMC",
            manufacturer=cls.manufacturer,
            style="",
            fuel="diesel",
            vehicle_group=cls.enviro200_group,
            active_production=False,
        )
        cls.enviro200ev = VehicleType.objects.create(
            name="Enviro200EV",
            manufacturer=cls.manufacturer,
            style="",
            fuel="electric",
            company="BYD ADL partnership",
            vehicle_group=cls.enviro200_group,
            active_production=True,
        )
        cls.chariots.group = cls.division
        cls.chariots.save(update_fields=["group"])
        cls.ceased_operator = Operator.objects.create(
            noc="CEAS",
            name="Ainsley Ceased",
            region_id="N",
            group=cls.division,
            ceased_operations_on=date(2022, 12, 31),
        )
        cls.preservation_group = PreservationGroup.objects.create(
            name="Ainsley Preservation Society",
            slug="ainsley-preservation-society",
            description="Preserving Ainsley buses.",
            website="https://example.com/preservation",
        )
        cls.preservation_user = User.objects.create(
            username="preserver",
            display_name="Preserver Person",
        )

        oyster = PaymentMethod.objects.create(
            name="oyster card", url="http://example.com"
        )
        euros = PaymentMethod.objects.create(name="euros")

        cls.chariots.payment_methods.set([oyster, euros])
        cls.service.operator.add(cls.chariots)
        cls.inactive_service.operator.add(cls.chariots)
        cls.inactive_service.non_current_route = True
        cls.inactive_service.save(update_fields=["non_current_route"])
        cls.event_service = Service.objects.create(
            service_code="event-1",
            line_name="E1",
            description="Festival Shuttle",
            region=cls.north,
            current=False,
            non_current_route=True,
        )
        cls.event_service.operator.add(cls.chariots)
        cls.event_route = Route.objects.create(
            service=cls.event_service,
            source=source,
            line_name="E1",
            event_start_date=date(2023, 3, 10),
            event_end_date=date(2023, 3, 12),
            event_visibility_weeks=4,
        )
        Vehicle.objects.create(
            code="ADLDEMO1",
            fleet_code="ADL1",
            reg="SN24ADL",
            vehicle_type=cls.enviro200ev,
            demonstrator=True,
            notes="Factory demonstrator",
        )
        Vehicle.objects.create(
            code="ADLNOTE1",
            fleet_code="ADL2",
            reg="SN24NOT",
            vehicle_type=cls.enviro200ev,
            notes="Demo bus but not flagged",
        )
        Vehicle.objects.create(
            code="1001",
            fleet_code="1001",
            reg="YX24BUS",
            operator=cls.chariots,
            vehicle_type=cls.enviro200,
        )
        Vehicle.objects.create(
            code="1002",
            fleet_code="1002",
            reg="YX24MMC",
            operator=cls.chariots,
            vehicle_type=cls.enviro200mmc,
        )
        Vehicle.objects.create(
            code="PRES200",
            fleet_code="P200",
            reg="A200ADL",
            operator=cls.chariots,
            vehicle_type=cls.enviro200,
            preserved=True,
            preservation_group=cls.preservation_group,
        )
        Vehicle.objects.create(
            code="PRES201",
            fleet_code="P201",
            reg="A201ADL",
            operator=cls.chariots,
            vehicle_type=cls.enviro200,
            preserved=True,
            preserved_by_user=cls.preservation_user,
        )
        Vehicle.objects.create(
            code="CEAS100",
            fleet_code="C100",
            reg="CE51 BUS",
            operator=cls.ceased_operator,
            vehicle_type=cls.enviro200,
        )

    def test_index(self):
        """Home page works and doesn't contain a breadcrumb"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Home")
        self.assertContains(response, "Ainsley Transport Group")
        self.assertContains(response, "Alexander Dennis")
        self.assertContains(response, "Ainsley Preservation Society")

    def test_manufacturer_page(self):
        response = self.client.get("/manufactors/alexander-dennis")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vehicle groups (1)")
        self.assertContains(response, "Demonstrator fleet (1)")
        self.assertContains(response, "Enviro200")
        self.assertContains(response, "Enviro200EV")
        self.assertContains(response, "Enviro200MMC")
        self.assertContains(response, "Vehicle group")
        self.assertContains(response, "Vehicle types")
        self.assertContains(response, "BYD ADL partnership")
        self.assertContains(response, "In production")
        self.assertContains(response, "2 exist")
        self.assertContains(response, "1 preserved")

    def test_manufacturer_page_groups_vehicle_types_under_vehicle_group(self):
        response = self.client.get("/manufactors/alexander-dennis")
        self.assertContains(response, '<h3 class="manufacturer-model-card__title">Enviro200</h3>', html=True)
        self.assertContains(response, ">Enviro200EV<", html=True)
        self.assertContains(response, ">Enviro200MMC<", html=True)
        self.assertNotContains(response, "0 demos")
        self.assertNotContains(response, "0 preserved")

    def test_manufacturer_sites_tab(self):
        response = self.client.get("/manufactors/alexander-dennis?tab=sites")
        self.assertContains(response, "Factories &amp; key buildings")
        self.assertContains(response, "Falkirk")
        self.assertContains(response, "Larbert HQ")

    def test_manufacturer_fleet_tab(self):
        response = self.client.get("/manufactors/alexander-dennis?tab=fleet")
        self.assertContains(response, "ADL1")
        self.assertNotContains(response, "ADL2")
        self.assertNotContains(response, "YX24 BUS")

    def test_robots_txt(self):
        response = self.client.get("/robots.txt")
        self.assertContains(response, "\n\nUser-agent: *\nDisallow: /\n")

        with override_settings(ALLOWED_HOSTS=["bustimes.org"]):
            response = self.client.get("/robots.txt", headers={"host": "bustimes.org"})
        self.assertContains(response, "User-agent: *\nDisallow:")

    def test_not_found(self):
        """Not found responses have a 404 status code"""
        response = self.client.get("/fff")
        self.assertEqual(response.status_code, 404)

    def test_static(self):
        for route in ("/cookies", "/data"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)

    def test_region(self):
        response = self.client.get("/regions/N")
        self.assertContains(response, "North")
        self.assertContains(response, "<h1>North</h1>")

        self.assertContains(
            response, "Chariots"
        )  # An operator with a current service should be listed
        self.assertNotContains(
            response, "Nu-Venture"
        )  # An operator with no current services should not be listed

        self.assertNotContains(response, '<a href="/areas/91">Norfolk</a>')
        self.assertNotContains(response, '<a href="/districts/91">North Norfolk</a>')

        self.melton_constable.district = self.north_norfolk
        self.melton_constable.save()
        response = self.client.get("/regions/N")
        self.assertNotContains(
            response, '<a href="/areas/91">Norfolk</a>'
        )  # Only one area in this region - so...
        self.assertContains(
            response, '<a href="/districts/91">North Norfolk</a>'
        )  # ...list the districts in the area

    def test_lowercase_region(self):
        response = self.client.get("/regions/n")
        self.assertContains(
            response, '<link rel="canonical" href="https://bustimes.org/regions/N">'
        )
        self.assertEqual(response.status_code, 200)

    def test_search(self):
        response = self.client.get("/search?q=melton")
        self.assertContains(response, "1 place")
        self.assertContains(response, "<b>Melton</b> Constable")
        self.assertContains(response, "/localities/melton-constable")

        response = self.client.get("/search")
        self.assertNotContains(response, "found for")

        response = self.client.get("/search?q=+")
        self.assertNotContains(response, "found for")

        services = Service.objects.with_documents()
        for service in services:
            service.search_vector = service.document
        Service.objects.bulk_update(services, ["search_vector"])

        response = self.client.get("/search?q=sandwich+deal")
        self.assertContains(response, "<b>Sandwich</b> - <b>Deal</b>")
        self.assertContains(
            response,
            '<li><a rel="next nofollow" href="?q=sandwich+deal&amp;page=2#services">2</a></li>',
        )

        response = self.client.get("/search?q=sandwich+deal&page=2")
        # explicity link to page 1
        self.assertContains(
            response,
            '<li><a rel="prev" href="?q=sandwich+deal&amp;page=1#services">1</a></li>',
        )

    def test_search_finds_operator_by_noc_without_vehicles(self):
        response = self.client.get("/search?q=AINS")
        self.assertContains(response, "/operators/ainsleys-chariots/vehicles")
        self.assertContains(response, "AINS")

    def test_search_includes_preservation_groups(self):
        response = self.client.get("/search?q=Preservation")
        self.assertContains(response, "Ainsley Preservation Society")
        self.assertContains(response, "/preservation-groups/ainsley-preservation-society/")

    def test_search_excludes_ceased_operator_from_active_results(self):
        response = self.client.get("/search?q=CEAS")
        self.assertNotContains(response, "Ainsley Ceased")

    def test_organisation(self):
        response = self.client.get("/organisations/ainsley-transport-group")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ATG")
        self.assertContains(response, "Ainsley Transport Group plc")
        self.assertContains(response, "Moving people across the region")
        self.assertContains(response, "Parent company for several local transport businesses.")
        self.assertContains(response, "Ainsley East")
        self.assertContains(response, "Ainsley&#x27;s Chariots")
        self.assertContains(response, "/groups/ainsley-east/vehicles")
        self.assertContains(response, "Ceased Operations")
        self.assertContains(response, "Ainsley Ceased")
        self.assertContains(response, "https://x.example/atg")
        self.assertContains(response, "https://linkedin.example/atg")

    def test_preservation_group_pages(self):
        response = self.client.get("/preservation-groups/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ainsley Preservation Society")
        self.assertContains(response, "1 preserved vehicle")

        response = self.client.get("/preservation-groups/ainsley-preservation-society/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preserving Ainsley buses.")
        self.assertContains(response, "P200")
        self.assertNotContains(response, "YX24 BUS")

    def test_user_profile_lists_preserved_vehicles(self):
        response = self.client.get(f"/accounts/users/{self.preservation_user.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preserved Vehicles")
        self.assertContains(response, "P201")

    def test_vehicles_browse_excludes_ceased_operators(self):
        response = self.client.get("/vehicles")
        self.assertContains(response, "Ainsley&#x27;s Chariots")
        self.assertNotContains(response, "Ainsley Ceased")

    def test_theme_css_uses_dark_mode_variables_for_profiles(self):
        css = (settings.BASE_DIR / "frontend" / "css" / "_base.scss").read_text()
        preservation_template = (
            settings.BASE_DIR
            / "busstops"
            / "templates"
            / "busstops"
            / "preservation_group_detail.html"
        ).read_text()
        self.assertNotIn("org-bg-mix, white", css)
        self.assertNotIn("division-bg-mix, white", css)
        self.assertIn("var(--card-background, var(--background-color))", preservation_template)

    def test_staff_stats(self):
        staff_user = User.objects.create(
            username="admin",
            email="admin@example.com",
            is_staff=True,
        )
        logged_in_user = User.objects.create(
            username="viewer",
            email="viewer@example.com",
        )

        anon_client = Client()
        anon_client.get("/")

        logged_in_client = Client()
        logged_in_client.force_login(logged_in_user)
        logged_in_client.get("/")

        response = self.client.get("/staff/stats")
        self.assertEqual(response.status_code, 302)

        self.client.force_login(staff_user)
        response = self.client.get("/staff/stats")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Site usage stats")
        self.assertContains(response, "5 minutes")
        self.assertContains(response, ">2<")

    def test_staff_stats_non_staff_hidden(self):
        user = User.objects.create(username="user", email="user@example.com")
        self.client.force_login(user)

        response = self.client.get("/staff/stats")

        self.assertEqual(response.status_code, 404)

    def test_api_search(self):
        response = self.client.get("/api/services/?search=holt").json()
        self.assertEqual(response["count"], 0)

        call_command("update_search_indexes")

        response = self.client.get("/api/services/?search=holt").json()
        self.assertEqual(response["count"], 1)

    def test_postcode(self):
        with vcr.use_cassette(
            str(settings.BASE_DIR / "fixtures" / "vcr" / "postcode.yaml"),
            decode_compressed_response=True,
        ):
            # postcode sufficiently near to fake locality
            response = self.client.get("/search?q=w1a 1aa")

            self.assertContains(response, "W1A 1AA")
            self.assertContains(
                response, """<a href="/map#16/51.5186/-0.1438">Map</a>"""
            )
            self.assertContains(response, "Melton Constable")
            self.assertContains(response, "/localities/melton-constable")
            self.assertNotContains(response, "results found for")

            # outcode
            with self.assertNumQueries(4):
                response = self.client.get("/search?q=nr1")
            self.assertContains(
                response, """<a href="/map#16/52.6265/1.3067">Map</a>"""
            )

            # postcode looks valid but doesn't exist
            with self.assertNumQueries(4):
                response = self.client.get("/search?q=w1a 1aj")
            self.assertNotContains(response, "Places near")

    def test_admin_area(self):
        """Admin area containing just one child should redirect to that child"""
        StopUsage.objects.create(service=self.service, stop=self.stop, order=0)
        response = self.client.get("/areas/91")
        self.assertRedirects(response, "/localities/melton-constable")

    def test_district(self):
        """Admin area containing just one child should redirect to that child"""
        response = self.client.get("/districts/91")
        self.assertEqual(response.status_code, 200)

    def test_locality(self):
        StopUsage.objects.create(service=self.service, stop=self.stop, order=0)
        response = self.client.get("/localities/e0048689")
        self.assertContains(response, "<h1>Melton Constable</h1>")
        self.assertContains(response, "/localities/melton-constable")

    def test_stops_api(self):
        response = self.client.get("/api/stops.json")
        self.assertEqual(
            response.json()["results"][0]["long_name"],
            "Melton Constable, adjacent to Bus Shelter",
        )

    def test_stops_json(self):
        # no params - bad request
        response = self.client.get("/stops.json")
        self.assertEqual(response.status_code, 400)

        # bounding box too big - bad request
        response = self.client.get(
            "/stops.json",
            {
                "ymax": "54.9",
                "xmax": "1.1",
                "ymin": "52.8",
                "xmin": "0",
            },
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.get(
            "/stops.json",
            {
                "ymax": "52.9",
                "xmax": "1.1",
                "ymin": "52.8",
                "xmin": "1.0",
            },
        )
        self.assertEqual("FeatureCollection", response.json()["type"])
        self.assertIn("features", response.json())

    def test_zoom_too_low(self):
        """zoom lower than 10"""

        response = self.client.get("/stops/9/255/255.pbf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/x-protobuf")
        self.assertEqual(response.content, b"")

    def test_empty_tile(self):
        """no stops"""

        response = self.client.get("/stops/14/0/0.pbf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/x-protobuf")
        self.assertEqual(response.content, b"")

    def test_tile_contains_active_stop(self):
        """A tile covering an active stop returns it (with current service only)"""

        response = self.client.get("/stops/14/8239/5347.pbf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/x-protobuf")
        # protobuf encodes strings as raw UTF-8 bytes
        self.assertIn(b"2900M114", response.content)
        self.assertIn(b"Melton Constable", response.content)
        # stop with inactive service must not appear
        self.assertNotIn(b"2900M115", response.content)

    def test_stop_view(self):
        response = self.client.get("/stops/2900m114")
        self.assertFalse(response.context_data["departures"])
        self.assertContains(response, "North")
        self.assertContains(response, "Norfolk")
        self.assertContains(response, "Melton Constable, opposite Bus Shelter")
        self.assertContains(response, "Features")
        self.assertContains(response, "Shelter")
        self.assertContains(response, "Accessibility")
        self.assertContains(response, "Step-free access")

    def test_grouped_stop_redirects_to_group_departures(self):
        group = StopGroup.objects.create(name="Melton Stands", slug="melton-stands")
        group.stops.add(self.stop)

        response = self.client.get("/stops/2900m114")

        self.assertRedirects(response, "/stop-groups/melton-stands", status_code=302)

    def test_stop_naptan_code_url(self):
        response = self.client.get("/stops/nfodgjtg")
        self.assertRedirects(response, "/stops/2900M114")

        response = self.client.get("/stops/nfodgjtgploop")
        self.assertEqual(response.status_code, 404)

    def test_inactive_stop(self):
        response = self.client.get("/stops/2900M115")
        self.assertContains(
            response,
            "<h1>Melton Constable, adjacent to Bus Shelter</h1>",
            status_code=404,
        )

    def test_operator_found(self):
        response = self.client.get("/operators/ains")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An airline operator")
        self.assertContains(response, "<h1>Ainsley&#x27;s Chariots</h1>")
        # postal address:
        # self.assertContains(response, "10 King Road<br />Ipswich", html=True)
        # obfuscated email address:
        # self.assertContains(
        #     response,
        #     "&#109;&#97;&#105;&#108;&#116;&#111;&#58;&#97;&#105;"
        #     + "&#110;&#115;&#108;&#101;&#121;&#64;&#101;&#120;&#97;&#109;"
        #     + "&#112;&#108;&#101;&#46;&#99;&#111;&#109;",
        # )
        self.assertContains(response, "http://www.ouibus.com")
        self.assertContains(response, "Non-current routes (2)")
        self.assertContains(response, "Festival Shuttle")
        self.assertContains(response, ">45A<")

    def test_operator_not_found(self):
        """An operator with no services, or that doesn't exist, should should return a 404 response"""
        with self.assertNumQueries(8):
            response = self.client.get("/operators/VENT")  # noc
            self.assertContains(response, "Nu-Venture", status_code=404)

        with self.assertNumQueries(8):
            response = self.client.get("/operators/nu-venture")  # slug
            self.assertContains(response, "Nu-Venture", status_code=404)

        with self.assertNumQueries(3):
            response = self.client.get("/operators/poop")  # doesn't exist
            self.assertEqual(response.status_code, 404)

        with self.assertNumQueries(1):
            response = self.client.get("/operators/POOP")
            self.assertEqual(response.status_code, 404)

    def test_service(self):
        RouteNotice.objects.create(
            service=self.service,
            title="Past works",
            description="Diversion via High Street",
            start="2023-01-01",
            end="2023-01-07",
            planned=True,
            diversion=True,
            diversion_num=12,
        )

        response = self.client.get("/services/45c-holt-norwich?tab=route-notices")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ouibus")
        self.assertContains(response, "Past works")
        self.assertContains(response, "Diversion via High Street")
        self.assertContains(response, "0012")
        # payment methods:
        self.assertContains(response, "euros")
        self.assertContains(response, "Oyster card")
        self.assertContains(response, '"http://example.com"')

        self.assertFalse(response.streaming)

        with override_settings(TEST=False):
            response = self.client.get("/services/45c-holt-norwich")
            self.assertTrue(response.streaming)

    def test_national_express_service(self):
        self.chariots.name = "National Express"
        self.chariots.url = "http://www.nationalexpress.com"
        self.chariots.save()

        response = self.client.get(self.service.get_absolute_url())
        self.assertNotContains(response, "Timing points")
        self.assertContains(response, "Melton Constable, opp Bus Shelter")

        # check for affiliate links
        self.assertEqual(
            response.context_data["links"][0],
            {
                "text": "Buy tickets at National Express",
                "url": "https://nationalexpress.prf.hn/click/camref:1011ljPYw/pubref:45C",
            },
        )

        response = self.client.get(self.chariots.get_absolute_url())
        self.assertContains(response, ">Tickets<")
        self.assertContains(
            response, "https://nationalexpress.prf.hn/click/camref:1011ljPYw", 2
        )

    def test_service_page_lists_service_specific_payment_methods(self):
        apple_pay = PaymentMethod.objects.create(name="apple pay")
        ServicePaymentMethod.objects.create(
            service=self.service, payment_method=apple_pay, accepted=True
        )
        euros = PaymentMethod.objects.get(name="euros")
        ServicePaymentMethod.objects.create(
            service=self.service, payment_method=euros, accepted=False
        )

        response = self.client.get(self.service.get_absolute_url())

        self.assertContains(response, "Payment methods")
        self.assertContains(response, "apple pay")
        self.assertContains(response, "accepted on this service")
        self.assertNotContains(response, "Oyster card")
        self.assertNotContains(response, "euros")

    def test_service_page_falls_back_to_operator_payment_methods_without_override(self):
        response = self.client.get(self.service.get_absolute_url())

        self.assertContains(response, "Payment methods")
        self.assertContains(response, "Oyster card")
        self.assertContains(response, "euros")

    def test_service_page_shows_free_service_message(self):
        free_service = PaymentMethod.objects.create(name="free service")
        ServicePaymentMethod.objects.create(
            service=self.service, payment_method=free_service, accepted=True
        )

        response = self.client.get(self.service.get_absolute_url())

        self.assertContains(response, "Payment methods")
        self.assertContains(response, "This service is free.")
        self.assertNotContains(response, "accepted on this service")

    def test_service_page_lists_accepted_tickets(self):
        dataset = DataSet.objects.create(name="Imported fares", published=True)
        tariff = Tariff.objects.create(
            code="Tariff@megapass",
            name="Tariff for Portsmouth 28 Day MegaRider",
            source=dataset,
            filename="megapass.xml",
        )
        tariff.operators.add(self.chariots)
        tariff.services.add(self.service)
        package = SalesOfferPackage.objects.create(name="Mobile App")
        product = PreassignedFareProduct.objects.create(
            name="Portsmouth 28 Day MegaRider",
            tariff_basis="zone",
        )
        FareTable.objects.create(
            code="fareTable@megapass",
            name="Portsmouth 28 Day MegaRider",
            tariff=tariff,
            sales_offer_package=package,
            preassigned_fare_product=product,
        )
        Price.objects.create(amount="70.00", tariff=tariff, sales_offer_package=package)

        response = self.client.get(self.service.get_absolute_url())

        self.assertContains(response, "Accepted tickets")
        self.assertContains(response, "Portsmouth 28 Day MegaRider")
        self.assertContains(response, "Mobile App: £70")
        self.assertContains(response, f"/fares/tariffs/{tariff.id}")

    def test_operator_tickets_tab_lists_imported_tickets(self):
        dataset = DataSet.objects.create(name="Imported fares", published=True)
        tariff = Tariff.objects.create(
            code="Tariff@megapass",
            name="Tariff for Portsmouth 28 Day MegaRider",
            source=dataset,
            filename="megapass.xml",
        )
        tariff.operators.add(self.chariots)
        package = SalesOfferPackage.objects.create(name="Mobile App")
        product = PreassignedFareProduct.objects.create(
            name="Portsmouth 28 Day MegaRider",
            tariff_basis="zone",
        )
        FareTable.objects.create(
            code="fareTable@megapass",
            name="Portsmouth 28 Day MegaRider",
            tariff=tariff,
            sales_offer_package=package,
            preassigned_fare_product=product,
        )
        Price.objects.create(amount="70.00", tariff=tariff, sales_offer_package=package)

        response = self.client.get(f"{self.chariots.get_detail_url()}?tab=tickets")

        self.assertContains(response, "Tickets (1)")
        self.assertContains(response, "Portsmouth 28 Day MegaRider")
        self.assertContains(response, "Mobile App: £70")
        self.assertContains(response, f"/fares/tariffs/{tariff.id}")

    def test_service_page_lists_manual_ticket(self):
        ticket = Ticket.objects.create(
            operator=self.chariots,
            ticket_type="Dayrider",
            name="Portsmouth Day Saver",
            description="Unlimited travel for one day.",
            zone="City",
            adult_price="7.00",
            child_price="3.50",
            days_valid_for=1,
        )
        TicketAcceptance.objects.create(
            ticket=ticket, service=self.service, accepted=True
        )

        response = self.client.get(self.service.get_absolute_url())

        self.assertContains(response, "Accepted tickets")
        self.assertContains(response, "Dayrider")
        self.assertContains(response, "Portsmouth Day Saver")
        self.assertContains(response, "City 1 day")
        self.assertContains(response, "A: Â£7 C: Â£3.50")
        self.assertContains(response, f"/fares/tickets/{ticket.id}")

    def test_operator_tickets_tab_lists_manual_ticket(self):
        ticket = Ticket.objects.create(
            operator=self.chariots,
            ticket_type="Dayrider",
            name="Portsmouth Day Saver",
            description="Unlimited travel for one day.",
            zone="City",
            adult_price="7.00",
            child_price="3.50",
            days_valid_for=1,
        )
        TicketAcceptance.objects.create(
            ticket=ticket, service=self.service, accepted=True
        )

        response = self.client.get(f"{self.chariots.get_detail_url()}?tab=tickets")

        self.assertContains(response, "Tickets (1)")
        self.assertContains(response, "Dayrider")
        self.assertContains(response, "Portsmouth Day Saver")
        self.assertContains(response, "City 1 day")
        self.assertContains(response, "A: Â£7 C: Â£3.50")
        self.assertContains(response, f"/fares/tickets/{ticket.id}")

    def test_operator_tickets_group_manual_tickets_by_ticket_type(self):
        first_ticket = Ticket.objects.create(
            operator=self.chariots,
            ticket_type="Dayrider",
            name="Ticket Name One",
            adult_price="2.50",
            child_price="1.00",
            zone="X",
            days_valid_for=1,
        )
        second_ticket = Ticket.objects.create(
            operator=self.chariots,
            ticket_type="Dayrider",
            name="Ticket Name Two",
            adult_price="4.00",
            child_price="2.00",
            zone="Y",
            days_valid_for=7,
        )
        TicketAcceptance.objects.create(
            ticket=first_ticket, service=self.service, accepted=True
        )
        TicketAcceptance.objects.create(
            ticket=second_ticket, service=self.service, accepted=True
        )

        response = self.client.get(f"{self.chariots.get_detail_url()}?tab=tickets")

        self.assertContains(response, '<h3><a href="/fares/tickets/%s">Dayrider</a></h3>' % first_ticket.id, html=True)
        self.assertContains(response, "2 ticket types")
        self.assertContains(response, "Ticket Name One")
        self.assertContains(response, "Ticket Name Two")
        self.assertContains(response, "A: Â£2.50 C: Â£1")
        self.assertContains(response, "A: Â£4 C: Â£2")
        self.assertContains(response, "zone X 1 day")
        self.assertContains(response, "zone Y 7 days")

    def test_operator_tickets_tab_lists_ticket_types_only(self):
        first_ticket = Ticket.objects.create(
            operator=self.chariots,
            ticket_type="Dayrider",
            name="Ticket Name One",
            adult_price="2.50",
            child_price="1.00",
            zone="X",
            days_valid_for=1,
        )
        second_ticket = Ticket.objects.create(
            operator=self.chariots,
            ticket_type="Dayrider",
            name="Ticket Name Two",
            adult_price="4.00",
            child_price="2.00",
            zone="Y",
            days_valid_for=7,
        )
        TicketAcceptance.objects.create(
            ticket=first_ticket, service=self.service, accepted=True
        )
        TicketAcceptance.objects.create(
            ticket=second_ticket, service=self.service, accepted=True
        )

        response = self.client.get(f"{self.chariots.get_detail_url()}?tab=tickets")

        self.assertContains(response, '<a href="/fares/tickets/%s">Dayrider</a>' % first_ticket.id)

    def test_service_redirect(self):
        """An inactive service should redirect to a current service with the same description"""
        with self.assertNumQueries(5):
            response = self.client.get("/services/45B")
        self.assertRedirects(response, "/services/45c-holt-norwich", status_code=301)

        response = self.client.get("/services/1-45-A-y08-9")
        self.assertEqual(response.status_code, 404)

    def test_not_found_redirect(self):
        """Redirect from url missing 'ea_' prefix"""
        response = self.client.get("/services/21-45-A-y08-9")
        self.assertRedirects(response, "/services/45c-holt-norwich")

    def test_service_not_found(self):
        """An inactive service with no replacement should redirect to its operator"""
        with self.assertNumQueries(6):
            response = self.client.get("/services/45A")
        self.assertRedirects(
            response, "/operators/ainsleys-chariots", status_code=302
        )

    def test_service_xml(self):
        """I can view the TransXChange XML for a service"""
        response = self.client.get("/services/foo/ea_21-45-A-y08.xml")
        self.assertEqual(response.status_code, 404)

    def test_service_map_data(self):
        # normal service
        with self.assertNumQueries(4):
            response = self.client.get(f"/services/{self.service.id}.json")
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.status_code, 200)

    def test_service_map_data_falls_back_to_stop_chain_route_links(self):
        second_stop = StopPoint.objects.create(
            atco_code="2900M116",
            common_name="Village Hall",
            active=True,
            admin_area=self.norfolk,
            locality=self.melton_constable,
            locality_centre=False,
            indicator="adj",
            bearing="E",
            latlong=Point(1.051894987727773, 52.86610279717982),
        )
        StopUsage.objects.create(service=self.service, stop=second_stop, order=1)
        RouteLink.objects.create(
            service=self.service,
            from_stop=self.stop,
            to_stop=second_stop,
            geometry="LINESTRING(1.041894987727773 52.85610279717982,1.046894987727773 52.86110279717982,1.051894987727773 52.86610279717982)",
            override=True,
        )

        response = self.client.get(f"/services/{self.service.id}.json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["geometry"]["type"], "MultiLineString")
        self.assertEqual(len(response.json()["geometry"]["coordinates"]), 1)
        self.assertEqual(len(response.json()["geometry"]["coordinates"][0]), 3)

    def test_route_editor_requires_staff(self):
        response = self.client.get("/services/route-editor")
        self.assertEqual(response.status_code, 302)

    def test_route_editor_search_and_save(self):
        staff_user = User.objects.create(username="staff", is_staff=True)
        self.client.force_login(staff_user)

        second_stop = StopPoint.objects.create(
            atco_code="2900M116",
            common_name="Village Hall",
            active=True,
            admin_area=self.norfolk,
            locality=self.melton_constable,
            locality_centre=False,
            indicator="adj",
            bearing="E",
            latlong=Point(1.051894987727773, 52.86610279717982),
        )
        StopUsage.objects.create(service=self.service, stop=second_stop, order=1)
        route = self.service.route_set.first()
        trip = route.trip_set.first()
        StopTime.objects.create(trip=trip, stop=second_stop, arrival="3")

        search_response = self.client.get("/services/route-editor/search?q=45C")
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(search_response.json()["results"][0]["id"], self.service.id)

        data_response = self.client.get(f"/services/{self.service.id}/route-editor.json")
        self.assertEqual(data_response.status_code, 200)
        payload = data_response.json()
        self.assertEqual(len(payload["segments"]), 1)

        save_response = self.client.post(
            f"/services/{self.service.id}/route-editor/save",
            data=json.dumps(
                {
                    "segments": [
                        {
                            "from_stop_id": self.stop.atco_code,
                            "to_stop_id": second_stop.atco_code,
                            "coordinates": [
                                [1.041894987727773, 52.85610279717982],
                                [1.046894987727773, 52.86110279717982],
                                [1.051894987727773, 52.86610279717982],
                            ],
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(save_response.status_code, 200)

        route_link = RouteLink.objects.get(
            service=self.service,
            from_stop=self.stop,
            to_stop=second_stop,
        )
        self.assertEqual(len(route_link.geometry.coords), 3)

    @patch("busstops.views.requests.get")
    def test_service_map_data_falls_back_to_bustimes_by_service_code(self, mock_get):
        self.service.stopusage_set.all().delete()

        search_response = Mock()
        search_response.raise_for_status.return_value = None
        search_response.json.return_value = {
            "results": [
                {
                    "id": 12345,
                    "slug": "45c-holt-norwich",
                    "service_code": "ea_21-45-A-y08",
                    "line_name": "45C",
                }
            ]
        }

        geometry_response = Mock()
        geometry_response.raise_for_status.return_value = None
        geometry_response.json.return_value = {
            "stops": {"type": "FeatureCollection", "features": []},
            "geometry": {
                "type": "LineString",
                "coordinates": [[1.0, 52.0], [1.1, 52.1]],
            },
        }

        mock_get.side_effect = [search_response, geometry_response]

        response = self.client.get(f"/services/{self.service.id}.json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["geometry"]["type"], "LineString")
        self.assertTrue(
            ServiceCode.objects.filter(
                service=self.service, scheme="bustimes-slug", code="45c-holt-norwich"
            ).exists()
        )

    @patch("busstops.views.requests.get")
    def test_route_map_tab_uses_bustimes_fallback(self, mock_get):
        self.service.stopusage_set.all().delete()

        search_response = Mock()
        search_response.raise_for_status.return_value = None
        search_response.json.return_value = {
            "results": [
                {
                    "id": 12345,
                    "slug": "45c-holt-norwich",
                    "service_code": "ea_21-45-A-y08",
                    "line_name": "45C",
                }
            ]
        }

        geometry_response = Mock()
        geometry_response.raise_for_status.return_value = None
        geometry_response.json.return_value = {
            "stops": {"type": "FeatureCollection", "features": []},
            "geometry": {
                "type": "LineString",
                "coordinates": [[1.0, 52.0], [1.1, 52.1]],
            },
        }

        mock_get.side_effect = [search_response, geometry_response]

        response = self.client.get(f"/services/{self.service.slug}?tab=route-map")
        self.assertContains(response, "Open route map")

    def test_modes(self):
        """A list of transport modes is turned into English"""
        self.assertContains(
            render(None, "modes.html", {"modes": ["bus"], "noun": "services"}),
            "Bus services",
        )
        self.assertContains(
            render(None, "modes.html", {"noun": "services"}), "Services"
        )
        self.assertContains(
            render(None, "modes.html", {"modes": ["bus", "coach"], "noun": "services"}),
            "Bus and coach services",
        )
        self.assertContains(
            render(
                None,
                "modes.html",
                {"modes": ["bus", "coach", "tram"], "noun": "services"},
            ),
            "Bus, coach and tram services",
        )
        self.assertContains(
            render(
                None,
                "modes.html",
                {"modes": ["bus", "coach", "tram", "cable car"], "noun": "operators"},
            ),
            "Bus, coach, tram and cable car operators",
        )

    def test_sitemap_index(self):
        with self.assertNumQueries(4):
            response = self.client.get("/sitemap.xml")
        self.assertContains(response, "https://testserver/sitemap-operators.xml")
        self.assertContains(response, "https://testserver/sitemap-services.xml")

    def test_sitemap_operators(self):
        with self.assertNumQueries(2):
            response = self.client.get("/sitemap-operators.xml")
        self.assertContains(
            response,
            "<url><loc>https://testserver/operators/ainsleys-chariots</loc><lastmod>2023-02-21</lastmod></url>",
        )

    def test_sitemap_services(self):
        with self.assertNumQueries(2):
            response = self.client.get("/sitemap-services.xml")
        self.assertContains(response, "https://testserver/services/45c-holt-norwich")

    def test_journey(self):
        """Journey planner"""
        with self.assertNumQueries(0):
            response = self.client.get("/journey")

        with self.assertNumQueries(1):
            response = self.client.get("/journey?from_q=melton")
        self.assertContains(response, "melton-constable")

        with self.assertNumQueries(1):
            response = self.client.get("/journey?to_q=melton")
        self.assertContains(response, "melton-constable")

        with self.assertNumQueries(2):
            response = self.client.get("/journey?from_q=melton&to_q=constable")

    def test_version(self):
        response = self.client.get("/version")
        self.assertTrue(response.content)

        with patch.dict("os.environ", {"COMMIT_HASH": "i've had a ploughman's"}):
            response = self.client.get("/version")
        self.assertEqual(
            response.content,
            b"<a href=\"https://github.com/jclgoodwin/bustimes.org/commit/i've had a ploughman's\">"
            b"i've had a ploughman's</a>",
        )

    def test_stop_qr_redirect(self):
        response = self.client.get("/STOP/2900ABC1")
        self.assertRedirects(response, "/stops/2900ABC1", 302, target_status_code=404)

    def test_trailing_slash(self):
        response = self.client.get("/map/")
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/mao/")
        self.assertEqual(response.status_code, 404)


class StopEditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(pk="N", name="North")
        admin_area = AdminArea.objects.create(
            id=91, atco_code=91, region=region, name="Norfolk"
        )
        locality = Locality.objects.create(
            id="E0048689",
            admin_area=admin_area,
            name="Melton Constable",
        )
        cls.stop = StopPoint.objects.create(
            atco_code="2900M114",
            common_name="Bus Shelter",
            active=True,
            admin_area=admin_area,
            locality=locality,
            indicator="opp",
            bearing="W",
            latlong=Point(1.041894987727773, 52.85610279717982),
        )
        cls.shelter = StopFeature.objects.create(name="Shelter")
        cls.ramp = StopFeature.objects.create(
            name="Step-free access",
            category=StopFeature.Category.ACCESSIBILITY,
        )
        cls.user = User.objects.create_user(
            username="stop-editor",
            password="secret",
            trusted=True,
        )
        cls.user.user_permissions.add(
            Permission.objects.get(codename="add_vehiclerevision")
        )

    def test_stop_page_links_to_edit_when_logged_in(self):
        self.client.force_login(self.user)

        response = self.client.get(self.stop.get_absolute_url())

        self.assertContains(response, self.stop.get_edit_url())
        self.assertContains(response, "Edit stop details")

    def test_edit_stop_updates_features_and_fields(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.stop.get_edit_url(),
            {
                "common_name": "Bus Stop",
                "indicator": self.stop.indicator,
                "landmark": "",
                "street": "",
                "crossing": "",
                "description": "",
                "notes": "",
                "features": [str(self.shelter.pk)],
                "accessibility_features": [str(self.ramp.pk)],
                "summary": "Stop has shelter and step-free access.",
            },
        )

        self.stop.refresh_from_db()
        self.assertContains(response, "Stop details updated.")
        self.assertEqual(self.stop.common_name, "Bus Stop")
        self.assertEqual(
            list(self.stop.features.order_by("id").values_list("name", flat=True)),
            ["Shelter", "Step-free access"],
        )


class VehicleNamePageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(pk="N", name="North")
        cls.operator = Operator.objects.create(
            noc="VENT",
            name="Nu-Venture",
            vehicle_mode="bus",
            region=cls.region,
        )
        cls.vehicle = Vehicle.objects.create(
            operator=cls.operator,
            code="1001",
            reg="YX24ABC",
            name="The Breeze",
        )
        cls.name_page = VehicleNamePage.objects.create(
            name="The Breeze",
            description="A commemorative fleet name used on selected vehicles.",
        )

    def test_vehicle_detail_links_matching_name_page(self):
        response = self.client.get(self.vehicle.get_absolute_url())

        self.assertContains(response, f'href="{self.name_page.get_absolute_url()}"')
        self.assertContains(response, "The Breeze")

    def test_vehicle_name_page_lists_matching_vehicles(self):
        response = self.client.get(self.name_page.get_absolute_url())

        self.assertContains(response, "A commemorative fleet name used on selected vehicles.")
        self.assertContains(response, self.vehicle.get_absolute_url())
        self.assertContains(response, str(self.vehicle))


class RouteNoticeDetailViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(pk="N", name="North")
        cls.source = DataSource.objects.create(name="EA")
        cls.service = Service.objects.create(
            service_code="ea_21-45-A-y08",
            line_name="45",
            description="Town Centre - Station",
            region=cls.region,
            slug="route-45",
        )
        cls.other_service = Service.objects.create(
            service_code="ea_21-46-A-y08",
            line_name="46",
            description="Market Square - Station",
            region=cls.region,
            slug="route-46",
        )
        cls.notice = RouteNotice.objects.create(
            service=cls.service,
            title="Town centre diversion",
            description="Buses are diverting via High Street until further notice.",
            start=date(2026, 5, 1),
            end=date(2026, 5, 31),
            planned=True,
            diversion=True,
            diversion_num=12,
        )
        cls.notice.other_services.add(cls.other_service)
        Route.objects.create(
            service=cls.service,
            source=cls.source,
            line_name="45",
        )
        Route.objects.create(
            service=cls.other_service,
            source=cls.source,
            line_name="46",
        )

    def test_service_route_notices_tab_hides_full_description(self):
        response = self.client.get(f"{self.service.get_absolute_url()}?tab=route-notices")

        self.assertContains(response, self.notice.get_absolute_url())
        self.assertNotContains(
            response,
            "Buses are diverting via High Street until further notice.",
        )

    def test_route_notice_detail_shows_full_description(self):
        response = self.client.get(self.notice.get_absolute_url())

        self.assertContains(response, "Town centre diversion")
        self.assertContains(
            response,
            "Buses are diverting via High Street until further notice.",
        )
        self.assertContains(response, self.service.get_absolute_url())
        self.assertContains(response, self.other_service.get_absolute_url())

    def test_related_service_route_notices_tab_includes_shared_notice(self):
        response = self.client.get(
            f"{self.other_service.get_absolute_url()}?tab=route-notices"
        )

        self.assertContains(response, self.notice.get_absolute_url())
        self.assertContains(response, "Town centre diversion")


class DisruptionOperatorBannerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(pk="N", name="North")
        cls.admin_area = AdminArea.objects.create(
            id=91, atco_code=91, region=cls.region, name="Norfolk"
        )
        cls.source = DataSource.objects.create(name="bustimes.org", url="https://example.com")
        cls.operator = Operator.objects.create(
            noc="VENT",
            name="Nu-Venture",
            vehicle_mode="bus",
            region=cls.region,
        )
        cls.service = Service.objects.create(
            service_code="ea_21-45-A-y08",
            line_name="45",
            description="Town Centre - Station",
            region=cls.region,
            slug="route-45-banner",
        )
        cls.service.operator.add(cls.operator)
        if DISRUPTIONS_AVAILABLE:
            cls.situation = Situation.objects.create(
                source=cls.source,
                summary="Town centre road closure",
                text="Diversions are in place around the market square.",
                predicted_cause="Emergency roadworks",
                predicted_end="2026-05-31T18:00:00Z",
            )
            cls.situation.affected_operators.add(cls.operator)
            cls.situation.affected_services.add(cls.service)
            cls.situation.affected_admin_areas.add(cls.admin_area)
        else:
            cls.situation = None

    def test_operator_page_shows_disruption_banner(self):
        if not DISRUPTIONS_AVAILABLE:
            self.skipTest("Disruptions models not available")
        response = self.client.get(self.operator.get_absolute_url())

        self.assertContains(response, "Service disruption affecting this operator")
        self.assertContains(response, self.situation.get_absolute_url())
        self.assertContains(response, "Town centre road closure")

    def test_disruption_detail_shows_extended_fields(self):
        if not DISRUPTIONS_AVAILABLE:
            self.skipTest("Disruptions models not available")
        response = self.client.get(self.situation.get_absolute_url())

        self.assertContains(response, "Predicted cause")
        self.assertContains(response, "Emergency roadworks")
        self.assertContains(response, "Predicted end")
        self.assertContains(response, self.operator.get_absolute_url())
        self.assertContains(response, self.service.get_absolute_url())
        self.assertContains(response, self.admin_area.get_absolute_url())
