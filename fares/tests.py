from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

import time_machine
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from vcr import use_cassette

from busstops.models import DataSource, Operator, Service
from bustimes.models import Route

from .admin import TicketAdminForm
from .management.commands.import_netex_fares import Command
from .models import DataSet, FareZone, Tariff, Ticket, TicketAcceptance, TimeInterval


class FaresTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a_c_williams = Operator.objects.create(noc="WMSA")
        cls.wm06 = Service.objects.create(line_name="wm06", current=True)
        source = DataSource.objects.create()
        Route.objects.create(line_name="wm06", service=cls.wm06, source=source)
        cls.wm06.operator.add(cls.a_c_williams)

    @time_machine.travel("2020-06-10", tick=False)
    def test_bod_netex(self):
        path = Path(__file__).resolve().parent / "data"

        with (
            use_cassette(str(path / "bod_fares.yaml")),
            self.assertLogs("fares.management.commands.import_netex_fares") as cm,
        ):
            call_command(
                "import_netex_fares", "XCpEBAoqPDfVdYRoUahb3F2nEZTJJCULXZCPo5x8"
            )

        self.assertEqual(
            cm.output,
            [
                "INFO:fares.management.commands.import_netex_fares:AC Williams_20201119 06:45:17",
                "WARNING:fares.management.commands.import_netex_fares:Service matching query does not exist. WMSA WM07",
                "INFO:fares.management.commands.import_netex_fares:  ⏱️ 0:00:00",
                "INFO:fares.management.commands.import_netex_fares:AC Williams_20201119 06:46:57",
                "INFO:fares.management.commands.import_netex_fares:  ⏱️ 0:00:00",
            ],
        )

        tariff = Tariff.objects.get(name="A C Williams WM06 - single fares")

        self.assertEqual(self.wm06, tariff.services.get())

        # tariff detail view
        response = self.client.get(tariff.get_absolute_url())

        self.assertContains(response, "A C Williams WM06 - single fares")
        self.assertContains(response, "<td>£1.70</td>")
        self.assertContains(response, "RAF Cranwell")

        origin = FareZone.objects.get(name="Welbourn", source=tariff.source)
        destination = FareZone.objects.get(name="Cranwell", source=tariff.source)
        response = self.client.get(
            f"{tariff.get_absolute_url()}?origin={origin.id}&destination={destination.id}"
        )

        self.assertContains(response, "<h3>Welbourn to Cranwell</h3>")
        self.assertContains(response, "<p>adult single: £1.50</p>")

        # dataset detail view
        url = tariff.source.get_absolute_url()
        response = self.client.get(url)
        self.assertContains(
            response,
            "Wednesday 30 September 2020\u2009\u2013\u2009Monday 30 September 2120",
        )
        response = self.client.get(
            f"{url}?origin={origin.id}&destination={destination.id}"
        )
        self.assertContains(response, "<h3>Welbourn to Cranwell</h3>")
        self.assertContains(response, "<p>adult single: £1.50</p>")

        # fares index
        response = self.client.get("/fares/")
        self.assertContains(response, "WM06 - Sleaford to Welbourn - Version 1")
        self.assertContains(response, "19 Nov 2020")

        self.assertEqual(TimeInterval.objects.count(), 0)

        tariff.source.published = True
        tariff.source.save(update_fields=["published"])

        # service detail view
        url = self.wm06.get_absolute_url()
        response = self.client.get(url)
        self.assertContains(response, ">Fare tables</")
        self.assertContains(response, ">A C Williams WM06 - single</option>")

        # service fares list view
        response = self.client.get(f"{url}/fares")
        self.assertContains(response, '<th colspan="8">Welbourn</th>')
        self.assertContains(response, '<th colspan="2">Greylees</th>')
        self.assertContains(response, '<th colspan="1">Ancaster</th')

        # fare table
        response = self.client.get(
            response.context["tariffs"][0].faretable_set.all()[0].get_absolute_url()
        )
        self.assertContains(response, '<th colspan="8">Welbourn</th>')
        self.assertContains(response, '<th colspan="2">Greylees</th>')
        self.assertContains(response, '<th colspan="1">Ancaster</th')

    def test_service_fares_not_found(self):
        response = self.client.get(f"{self.wm06.get_absolute_url()}/fares")
        self.assertEqual(response.status_code, HTTPStatus.NOT_FOUND)

    def test_manual_ticket_detail_lists_accepted_services(self):
        ticket = Ticket.objects.create(
            operator=self.a_c_williams,
            ticket_type="Dayrider",
            name="City Day Saver",
            description="Unlimited travel for one day.",
            zone="Town",
            adult_price="6.50",
            child_price="3.25",
            days_valid_for=1,
        )
        TicketAcceptance.objects.create(ticket=ticket, service=self.wm06, accepted=True)

        response = self.client.get(ticket.get_absolute_url())

        self.assertContains(response, "City Day Saver")
        self.assertContains(response, "Unlimited travel for one day.")
        self.assertContains(response, "Ticket type: Dayrider")
        self.assertContains(response, "Zone: Town")
        self.assertContains(response, "Adult price: £6.50")
        self.assertContains(response, "Child price: £3.25")
        self.assertContains(response, "Days valid for: 1")
        self.assertContains(response, "Accepted on these routes")
        self.assertContains(response, self.wm06.get_absolute_url())

    def test_ticket_admin_form_limits_and_saves_operator_services(self):
        wm07 = Service.objects.create(line_name="wm07", current=True)
        wm07.operator.add(self.a_c_williams)

        other_operator = Operator.objects.create(noc="OTHR", name="Other Operator")
        other_service = Service.objects.create(line_name="other1", current=True)
        other_service.operator.add(other_operator)

        form = TicketAdminForm(
            data={
                "operator": self.a_c_williams.pk,
                "ticket_type": "Dayrider",
                "name": "City Day Saver",
                "description": "Unlimited travel for one day.",
                "zone": "Town",
                "adult_price": "6.50",
                "child_price": "3.25",
                "days_valid_for": "1",
                "accepted_services": [str(self.wm06.pk)],
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            list(form.fields["accepted_services"].queryset),
            [self.wm06, wm07],
        )

        ticket = form.save()

        self.assertEqual(ticket.operator, self.a_c_williams)
        self.assertEqual(ticket.ticket_type, "Dayrider")
        self.assertEqual(ticket.zone, "Town")
        self.assertEqual(str(ticket.adult_price), "6.50")
        self.assertEqual(str(ticket.child_price), "3.25")
        self.assertEqual(ticket.days_valid_for, 1)
        self.assertCountEqual(
            list(
                TicketAcceptance.objects.filter(ticket=ticket, accepted=True).values_list(
                    "service_id", flat=True
                )
            ),
            [self.wm06.pk],
        )
        self.assertEqual(
            TicketAcceptance.objects.get(ticket=ticket, service=wm07).accepted, False
        )
        self.assertFalse(
            TicketAcceptance.objects.filter(ticket=ticket, service=other_service).exists()
        )

    def test_manual_ticket_type_detail_lists_grouped_tickets_with_padded_prices(self):
        first_ticket = Ticket.objects.create(
            operator=self.a_c_williams,
            ticket_type="Dayrider",
            name="City Day Saver",
            zone="Town",
            adult_price="6.50",
            child_price="3.25",
            days_valid_for=1,
        )
        second_ticket = Ticket.objects.create(
            operator=self.a_c_williams,
            ticket_type="Dayrider",
            name="City Week Saver",
            zone="Town",
            adult_price="18.00",
            child_price="9.00",
            days_valid_for=7,
        )
        TicketAcceptance.objects.create(ticket=first_ticket, service=self.wm06, accepted=True)
        TicketAcceptance.objects.create(ticket=second_ticket, service=self.wm06, accepted=True)

        response = self.client.get(first_ticket.get_absolute_url())

        self.assertContains(response, "<h1>Dayrider</h1>", html=True)
        self.assertContains(response, "City Day Saver")
        self.assertContains(response, "City Week Saver")
        self.assertContains(response, "Â£6.50 adult")
        self.assertContains(response, "Â£18.00 adult")
        self.assertContains(response, "Â£9.00 child")
        self.assertContains(response, "7 days")

    def test_netex_preview(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "data"
            / "FX_PI_01_UK_SCTE_LINE_FARE_Line-59t@Outbound_wef-20220208_20220211-0936.xml"
        )
        uploaded = SimpleUploadedFile(
            fixture_path.name,
            fixture_path.read_bytes(),
            content_type="application/xml",
        )

        response = self.client.post("/fares/preview", {"file": uploaded})

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertContains(response, "Preview NeTEx fare data")
        self.assertContains(response, "Fares for Line 59t")
        self.assertContains(response, "Distance matrix for line Line_59t@Outbound")
        self.assertContains(response, "Hpool Adult Single Zone")
        self.assertContains(response, "StocktonHighSt")
        self.assertContains(response, "£1.2")

    def test_stagecoach_network_import_links_services_and_prices(self):
        command = Command()
        command.user_profiles = {}
        command.sales_offer_packages = {}
        command.fare_products = {}
        command.fare_zones = {}

        source = DataSet.objects.create(name="Stagecoach sample")
        xml = b"""<?xml version="1.0" encoding="utf-8"?>
<PublicationDelivery xmlns="http://www.netex.org.uk/netex">
  <dataObjects>
    <CompositeFrame>
      <frames>
        <ResourceFrame>
          <organisations>
            <Operator id="noc:WMSA">
              <Name>A C Williams</Name>
            </Operator>
          </organisations>
        </ResourceFrame>
        <ServiceFrame>
          <lines>
            <Line id="Line@wm06">
              <Name>WM06</Name>
              <PublicCode>wm06</PublicCode>
              <OperatorRef ref="noc:WMSA">noc:WMSA</OperatorRef>
            </Line>
          </lines>
        </ServiceFrame>
        <FareFrame>
          <salesOfferPackages>
            <SalesOfferPackage id="SOP@mobile">
              <Name>Mobile App</Name>
            </SalesOfferPackage>
            <SalesOfferPackage id="SOP@web">
              <Name>Smartcard Online</Name>
            </SalesOfferPackage>
          </salesOfferPackages>
          <fareProducts>
            <PreassignedFareProduct id="product@megapass">
              <Name>City Mega Pass</Name>
              <Description>Unlimited travel in the city zone</Description>
            </PreassignedFareProduct>
          </fareProducts>
          <tariffs>
            <Tariff id="Tariff@megapass">
              <Name>Tariff for City Mega Pass</Name>
              <OperatorRef ref="noc:WMSA">noc:WMSA</OperatorRef>
              <TypeOfTariffRef ref="fxc:zonal" />
            </Tariff>
          </tariffs>
          <fareTables>
            <FareTable id="fareTable@megapass">
              <Name>City Mega Pass</Name>
              <usedIn>
                <TariffRef ref="Tariff@megapass" />
              </usedIn>
              <pricesFor>
                <PreassignedFareProductRef ref="product@megapass" />
                <SalesOfferPackageRef ref="SOP@mobile" />
                <SalesOfferPackageRef ref="SOP@web" />
              </pricesFor>
              <prices>
                <DistanceMatrixElementPrice id="price@megapass">
                  <Amount>28</Amount>
                </DistanceMatrixElementPrice>
              </prices>
            </FareTable>
          </fareTables>
        </FareFrame>
      </frames>
    </CompositeFrame>
  </dataObjects>
</PublicationDelivery>
"""

        command.handle_file(source, BytesIO(xml), "stagecoach-network.xml")

        tariff = Tariff.objects.get(code="Tariff@megapass")
        self.assertEqual(tariff.operators.get(), self.a_c_williams)
        self.assertEqual(tariff.services.get(), self.wm06)
        self.assertEqual(tariff.price_set.count(), 2)
        self.assertEqual(tariff.faretable_set.get().preassigned_fare_product.name, "City Mega Pass")

    def test_import_netex_directory(self):
        xml = b"""<?xml version="1.0" encoding="utf-8"?>
<PublicationDelivery xmlns="http://www.netex.org.uk/netex">
  <dataObjects>
    <CompositeFrame>
      <Name>Bulk import sample</Name>
      <frames>
        <ResourceFrame>
          <organisations>
            <Operator id="noc:WMSA">
              <Name>A C Williams</Name>
            </Operator>
          </organisations>
        </ResourceFrame>
        <ServiceFrame>
          <lines>
            <Line id="Line@wm06">
              <Name>WM06</Name>
              <PublicCode>wm06</PublicCode>
              <OperatorRef ref="noc:WMSA">noc:WMSA</OperatorRef>
            </Line>
          </lines>
        </ServiceFrame>
        <FareFrame>
          <fareProducts>
            <PreassignedFareProduct id="product@megapass">
              <Name>City Mega Pass</Name>
            </PreassignedFareProduct>
          </fareProducts>
          <tariffs>
            <Tariff id="Tariff@megapass">
              <Name>Tariff for City Mega Pass</Name>
              <OperatorRef ref="noc:WMSA">noc:WMSA</OperatorRef>
            </Tariff>
          </tariffs>
          <fareTables>
            <FareTable id="fareTable@megapass">
              <Name>City Mega Pass</Name>
              <usedIn>
                <TariffRef ref="Tariff@megapass" />
              </usedIn>
              <pricesFor>
                <PreassignedFareProductRef ref="product@megapass" />
              </pricesFor>
              <prices>
                <DistanceMatrixElementPrice id="price@megapass">
                  <Amount>28</Amount>
                </DistanceMatrixElementPrice>
              </prices>
            </FareTable>
          </fareTables>
        </FareFrame>
      </frames>
    </CompositeFrame>
  </dataObjects>
</PublicationDelivery>
"""
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.xml"
            path.write_bytes(xml)

            call_command("import_netex_directory", temp_dir)

        tariff = Tariff.objects.get(code="Tariff@megapass")
        self.assertEqual(tariff.operators.get(), self.a_c_williams)
        self.assertEqual(tariff.services.get(), self.wm06)
        self.assertTrue(tariff.source.url.startswith("file:///"))

    def test_import_netex_directory_zip_files(self):
        xml = b"""<?xml version="1.0" encoding="utf-8"?>
<PublicationDelivery xmlns="http://www.netex.org.uk/netex">
  <dataObjects>
    <CompositeFrame>
      <Name>Bulk zip sample</Name>
      <frames>
        <ResourceFrame>
          <organisations>
            <Operator id="noc:WMSA">
              <Name>A C Williams</Name>
            </Operator>
          </organisations>
        </ResourceFrame>
        <ServiceFrame>
          <lines>
            <Line id="Line@wm06">
              <Name>WM06</Name>
              <PublicCode>wm06</PublicCode>
              <OperatorRef ref="noc:WMSA">noc:WMSA</OperatorRef>
            </Line>
          </lines>
        </ServiceFrame>
        <FareFrame>
          <fareProducts>
            <PreassignedFareProduct id="product@megapasszip">
              <Name>City Mega Pass Zip</Name>
            </PreassignedFareProduct>
          </fareProducts>
          <tariffs>
            <Tariff id="Tariff@megapasszip">
              <Name>Tariff for City Mega Pass Zip</Name>
              <OperatorRef ref="noc:WMSA">noc:WMSA</OperatorRef>
            </Tariff>
          </tariffs>
          <fareTables>
            <FareTable id="fareTable@megapasszip">
              <Name>City Mega Pass Zip</Name>
              <usedIn>
                <TariffRef ref="Tariff@megapasszip" />
              </usedIn>
              <pricesFor>
                <PreassignedFareProductRef ref="product@megapasszip" />
              </pricesFor>
              <prices>
                <DistanceMatrixElementPrice id="price@megapasszip">
                  <Amount>31</Amount>
                </DistanceMatrixElementPrice>
              </prices>
            </FareTable>
          </fareTables>
        </FareFrame>
      </frames>
    </CompositeFrame>
  </dataObjects>
</PublicationDelivery>
"""
        with TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "sample.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("nested/sample.xml", xml)

            call_command("import_netex_directory", temp_dir)

        tariff = Tariff.objects.get(code="Tariff@megapasszip")
        self.assertEqual(tariff.operators.get(), self.a_c_williams)
        self.assertEqual(tariff.services.get(), self.wm06)
        self.assertIn("sample.zip!/", tariff.source.url)

    def test_ad_hoc(self):
        command = Command()
        command.user_profiles = {}
        command.sales_offer_packages = {}
        command.fare_products = {}
        command.fare_zones = {}

        source = DataSet.objects.create()

        base_path = Path(__file__).resolve().parent / "data"

        for filename, number in (
            ("connexions_Harrogate_Coa_16.286Z_IOpbaMX.xml", 42),
            ("FLDSa0eb4e10_1605250801329.xml", 22),
            (
                "KBUS_FF_ArrivaAdd-on_2Multi_6d7e341a-0680-4397-9b3f-90a290087494_637613495098903655.xml",
                12,
            ),
            (
                "FECS_23A_Outbound_YPSingle_6764fa3b-4b05-4331-9bea-c7bb90212531_637829447220443476.xml",
                30,
            ),
            ("LYNX 39 single.xml", 27),
            ("LYNX Coast.xml", 75),
            ("LYNX Townrider.xml", None),
            (
                "NADS_103A_Inbound_AdultReturn_aae41d08-15c5-4fef-bf58-e8188410605e_637503825593765582.xml",
                None,
            ),
            ("STBC96615325_1597249888210_YFXY9eP.xml", None),
            ("TGTC238e19ce_1603195065008_yJWka80.xml", None),
            ("TWGT0b3b32d1_1600857778793_2gKCmVT_2.xml", None),
            ("FX_PI_01_UK_SCTE_PRODUCTS_COMMON_wef-20220208_20220211-0936.xml", None),
            (
                "FX_PI_01_UK_SCTE_LINE_FARE_Line-59t@Outbound_wef-20220208_20220211-0936.xml",
                None,
            ),
        ):
            path = base_path / filename

            with path.open() as open_file:
                if number is None:
                    command.handle_file(source, open_file, filename)
                else:
                    with number and self.assertNumQueries(number):
                        command.handle_file(source, open_file, filename)

        tariff = Tariff.objects.get(
            filename="KBUS_FF_ArrivaAdd-on_2Multi_6d7e341a-0680-4397-9b3f-90a290087494_637613495098903655.xml"
        )
        self.assertEqual(
            str(tariff.valid_between),
            "[2021-07-08 00:00:00+00:00, 2121-07-08 00:00:00+00:00]",
        )


class ImportMobileProductsCommandTests(TestCase):
    def test_imports_mobile_products_into_manual_tickets(self):
        operator = Operator.objects.create(noc="BHBC", name="Brighton & Hove")
        csv_text = """category_id,category_title,category_description,topup_id,topup_title,topup_description,topup_price_in_pence,topup_entitlement_type,topup_entitlement_unit,topup_entitlement_value,topup_entitlement_quantity,topup_entitlement_start_date,topup_entitlement_end_date,topup_passenger_class_id,topup_passenger_class_name,topup_passenger_class_quantity
cat1,citySAVER Tickets - Adult,Adult city tickets,top1,24 hour Adult citySAVER,Use for 24 hours,630,flexible,days,1,1,,,adult,Adult,1
cat2,citySAVER Tickets - Student,Student city tickets,top2,24 hour Student citySAVER,Use for 24 hours,460,flexible,days,1,1,,,student,Student,1
"""
        with TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "mobile_products.csv"
            csv_path.write_text(csv_text, encoding="utf-8")

            call_command(
                "import_mobile_products",
                str(csv_path),
                operator=operator.noc,
            )

        adult_ticket = Ticket.objects.get(
            operator=operator,
            ticket_type="citySAVER Tickets - Adult",
            name="24 hour Adult citySAVER",
        )
        student_ticket = Ticket.objects.get(
            operator=operator,
            ticket_type="citySAVER Tickets - Student",
            name="24 hour Student citySAVER",
        )

        self.assertEqual(str(adult_ticket.adult_price), "6.30")
        self.assertEqual(adult_ticket.days_valid_for, 1)
        self.assertIsNone(adult_ticket.child_price)
        self.assertIn("Passenger class: Adult.", adult_ticket.description)

        self.assertIsNone(student_ticket.adult_price)
        self.assertIsNone(student_ticket.child_price)
        self.assertEqual(student_ticket.days_valid_for, 1)
        self.assertIn("Passenger class: Student.", student_ticket.description)
        self.assertIn("Price: £4.60.", student_ticket.description)

    def test_reimport_updates_existing_ticket_without_duplicates(self):
        operator = Operator.objects.create(noc="BHBC", name="Brighton & Hove")
        csv_text = """category_id,category_title,category_description,topup_id,topup_title,topup_description,topup_price_in_pence,topup_entitlement_type,topup_entitlement_unit,topup_entitlement_value,topup_entitlement_quantity,topup_entitlement_start_date,topup_entitlement_end_date,topup_passenger_class_id,topup_passenger_class_name,topup_passenger_class_quantity
cat1,citySAVER Tickets - Adult,Adult city tickets,top1,24 hour Adult citySAVER,Use for 24 hours,630,flexible,days,1,1,,,adult,Adult,1
"""
        updated_csv_text = csv_text.replace(",630,", ",650,")

        with TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "mobile_products.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            call_command(
                "import_mobile_products",
                str(csv_path),
                operator=operator.noc,
            )

            csv_path.write_text(updated_csv_text, encoding="utf-8")
            call_command(
                "import_mobile_products",
                str(csv_path),
                operator=operator.noc,
            )

        self.assertEqual(Ticket.objects.count(), 1)
        ticket = Ticket.objects.get()
        self.assertEqual(str(ticket.adult_price), "6.50")
