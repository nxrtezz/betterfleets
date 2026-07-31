from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import TestCase

from busstops.models import DataSource, Operator, Region, Service, ServiceCode


def make_response(payload):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


class ReconcileBustimesServiceSlugsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(id="GB", name="Great Britain")
        cls.operator = Operator.objects.create(
            noc="NATX",
            name="National Express",
            slug="national-express",
        )
        cls.bustimes_source = DataSource.objects.create(
            name="Bustimes API",
            url="https://bustimes.org/api/",
        )
        cls.other_source = DataSource.objects.create(name="Imported BODS")

    def create_service(self, *, slug, source, line_name="007", description="Old desc"):
        service = Service.objects.create(
            slug=slug,
            service_code="old-code",
            line_name=line_name,
            description=description,
            current=True,
            source=source,
            region=self.region,
        )
        service.operator.add(self.operator)
        ServiceCode.objects.create(service=service, scheme="bustimes-slug", code=slug)
        return service

    def test_updates_slug_and_details_when_bustimes_differs(self):
        service = self.create_service(
            slug="old-007-london-dover",
            source=self.other_source,
            description="London - Dover",
        )

        with patch(
            "busstops.management.commands.reconcile_bustimes_service_slugs.requests.get",
            return_value=make_response(
                {
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [
                        {
                            "id": 2,
                            "slug": "007-london-dover-town-centre",
                            "line_name": "007",
                            "description": "London - Dover (Town Centre)",
                            "region_id": "GB",
                            "mode": "coach",
                            "operator": ["NATX"],
                            "modified_at": "2026-04-18T02:14:28.394852+01:00",
                        }
                    ],
                }
            ),
        ):
            call_command("reconcile_bustimes_service_slugs", apply=True)

        service.refresh_from_db()
        self.assertEqual(service.slug, "007-london-dover-town-centre")
        self.assertEqual(service.line_name, "007")
        self.assertEqual(service.description, "London - Dover (Town Centre)")
        self.assertEqual(service.mode, "coach")
        self.assertTrue(
            service.servicecode_set.filter(
                scheme="bustimes-slug", code="007-london-dover-town-centre"
            ).exists()
        )

    def test_deletes_missing_service_only_when_it_originated_from_bustimes(self):
        service = self.create_service(
            slug="gone-service",
            source=self.bustimes_source,
        )

        with patch(
            "busstops.management.commands.reconcile_bustimes_service_slugs.requests.get",
            return_value=make_response(
                {"count": 0, "next": None, "previous": None, "results": []}
            ),
        ):
            call_command("reconcile_bustimes_service_slugs", apply=True)

        self.assertFalse(Service.objects.filter(pk=service.pk).exists())

    def test_preserves_missing_service_when_it_did_not_originate_from_bustimes(self):
        service = self.create_service(
            slug="missing-but-local",
            source=self.other_source,
        )
        stdout = StringIO()

        with patch(
            "busstops.management.commands.reconcile_bustimes_service_slugs.requests.get",
            return_value=make_response(
                {"count": 0, "next": None, "previous": None, "results": []}
            ),
        ):
            call_command(
                "reconcile_bustimes_service_slugs",
                apply=True,
                stdout=stdout,
            )

        self.assertTrue(Service.objects.filter(pk=service.pk).exists())
        self.assertIn("preserved because source is not", stdout.getvalue())

    def test_merges_into_existing_service_when_remote_slug_already_exists(self):
        duplicate = self.create_service(
            slug="old-1-hardgunwharf",
            source=self.other_source,
            description="Old duplicate description",
        )
        canonical = self.create_service(
            slug="1-the-hardgunwharf-south-parade-pier-2",
            source=self.other_source,
            description="Stale canonical description",
        )

        with patch(
            "busstops.management.commands.reconcile_bustimes_service_slugs.requests.get",
            return_value=make_response(
                {
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [
                        {
                            "id": 12,
                            "slug": "1-the-hardgunwharf-south-parade-pier-2",
                            "line_name": "1",
                            "description": "The Hard/ Gunwharf - South Parade Pier",
                            "region_id": "GB",
                            "mode": "bus",
                            "operator": ["NATX"],
                        }
                    ],
                }
            ),
        ):
            call_command("reconcile_bustimes_service_slugs", apply=True)

        self.assertFalse(Service.objects.filter(pk=duplicate.pk).exists())
        canonical.refresh_from_db()
        self.assertEqual(canonical.slug, "1-the-hardgunwharf-south-parade-pier-2")
        self.assertEqual(
            canonical.description,
            "The Hard/ Gunwharf - South Parade Pier",
        )
        self.assertTrue(
            canonical.servicecode_set.filter(
                scheme="slug",
                code="old-1-hardgunwharf",
            ).exists()
        )
