from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.test import TestCase
from django.forms.models import modelform_factory

from busstops.models import AdminArea, DataSource, Operator, Region, Service

from .models import Consequence, Situation, ValidityPeriod


class DisruptionsTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        source = Situation.source.field.remote_field.model.objects.create(
            name="Test", url="http://example.com"
        )
        cls.situation = Situation.objects.create(
            source=source,
            summary="A pigeon got in the cab and bit the driver",
            publication_window=DateTimeTZRange(
                "2021-05-10T09:00:00Z", "2021-05-10T10:00:00Z", "[]"
            ),
        )

    def test_validity_periods_daily(self):
        self.assertEqual(self.situation.list_validity_periods(), [])
        ValidityPeriod.objects.bulk_create(
            [
                ValidityPeriod(
                    situation=self.situation,
                    period=DateTimeTZRange(
                        "2021-05-10T09:00:00Z", "2021-05-10T10:00:00Z", "[]"
                    ),
                ),
                ValidityPeriod(
                    situation=self.situation,
                    period=DateTimeTZRange(
                        "2021-05-11T09:00:00Z", "2021-05-11T10:00:00Z", "[]"
                    ),
                ),
            ]
        )
        self.assertEqual(
            self.situation.list_validity_periods(),
            [
                "10:00\u2009\u2013\u200911:00,\nMonday 10\u2009\u2013\u2009Tuesday 11 May 2021"
            ],
        )

    def test_validity_periods_nightly(self):
        self.assertEqual(self.situation.list_validity_periods(), [])
        ValidityPeriod.objects.bulk_create(
            [
                ValidityPeriod(
                    situation=self.situation,
                    period=DateTimeTZRange(
                        "2021-05-10T20:00:00Z", "2021-05-11T06:00:00Z", "[]"
                    ),
                ),
                ValidityPeriod(
                    situation=self.situation,
                    period=DateTimeTZRange(
                        "2021-05-11T20:00:00Z", "2021-05-12T06:00:00Z", "[]"
                    ),
                ),
            ]
        )
        self.assertEqual(
            self.situation.list_validity_periods(),
            [
                "21:00\u2009\u2013\u200907:00,\nMonday 10\u2009\u2013\u2009Wednesday 12 May 2021"
            ],
        )

    def test_combined_affected_objects_include_manual_and_consequence_links(self):
        region = Region.objects.create(pk="N", name="North")
        admin_area = AdminArea.objects.create(
            id=91, atco_code=91, region=region, name="Norfolk"
        )
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator",
            vehicle_mode="bus",
            region=region,
        )
        service = Service.objects.create(
            service_code="T1",
            line_name="1",
            description="Town - Station",
            region=region,
        )

        self.situation.affected_operators.add(operator)
        self.situation.affected_services.add(service)
        self.situation.affected_admin_areas.add(admin_area)

        consequence = Consequence.objects.create(situation=self.situation)
        consequence.operators.add(operator)
        consequence.services.add(service)

        self.assertEqual(list(self.situation.get_affected_operators()), [operator])
        self.assertEqual(list(self.situation.get_affected_services()), [service])
        self.assertEqual(list(self.situation.get_affected_admin_areas()), [admin_area])

    def test_situation_form_allows_arbitrary_data_source(self):
        source = DataSource.objects.create(
            name="Ray Stenning's Bus Impact", url="https://example.com"
        )
        form_class = modelform_factory(
            Situation,
            fields=["source", "summary", "publication_window"],
        )
        form = form_class(
            data={
                "source": source.pk,
                "summary": "Road Traffic Collision - Central Southampton",
                "publication_window": "",
            }
        )

        self.assertIn(source, form.fields["source"].queryset)
