from datetime import date
from django.test import TestCase
from busstops.models import DataSource, Operator, Service
from bustimes.models import Route, Trip, TimetableDataSource, Version
from busstops.service_selection import prefer_svct_timetables


class SvctServiceSelectionTests(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(noc="SVCT", name="Southern Vectis")
        self.bods = DataSource.objects.create(name="Published timetable")
        self.passenger = DataSource.objects.create(name="Passenger export")
        provider = TimetableDataSource.objects.create(name="Passenger")
        self.version = Version.objects.create(source=provider, start_date=date(2020, 1, 1), end_date=date(2099, 1, 1), name="v1")

    def service(self, source, line="1", description="Newport - Cowes", operator=None, start=None, with_trip=True):
        s = Service.objects.create(source=source, line_name=line, description=description, current=True)
        s.operator.add(operator or self.operator)
        r = Route.objects.create(source=source, service=s, code=str(s.pk), version=self.version if source==self.passenger else None, start_date=start or date(2020, 1, 1), end_date=date(2099, 1, 1))
        if with_trip:
            Trip.objects.create(route=r, start=3600, end=7200)
        return s

    def selected(self):
        return set(prefer_svct_timetables(Service.objects.filter(current=True), date(2026, 11, 14)).values_list("pk", flat=True))

    def test_duplicate_prefers_published_timetable(self):
        preferred = self.service(self.bods)
        duplicate = self.service(self.passenger)
        self.assertEqual(self.selected(), {preferred.pk})
        self.assertTrue(Service.objects.filter(pk=duplicate.pk).exists())

    def test_unique_passenger_line_is_preserved(self):
        a = self.service(self.bods)
        b = self.service(self.passenger, line="200")
        self.assertEqual(self.selected(), {a.pk,b.pk})

    def test_description_drift_does_not_duplicate_same_public_line(self):
        a=self.service(self.bods)
        b=self.service(self.passenger,description="Newport - Ryde")
        self.assertEqual(self.selected(),{a.pk})

    def test_other_operator_is_unchanged(self):
        other=Operator.objects.create(noc="OTHER", name="Other")
        a=self.service(self.bods,operator=other)
        b=self.service(self.passenger,operator=other)
        self.assertEqual(self.selected(),{a.pk,b.pk})

    def test_empty_preferred_feed_keeps_fallback(self):
        a=self.service(self.bods,with_trip=False)
        b=self.service(self.passenger)
        self.assertEqual(self.selected(),{a.pk,b.pk})

    def test_future_preferred_feed_keeps_current_fallback(self):
        a=self.service(self.bods,start=date(2027,1,1))
        b=self.service(self.passenger)
        self.assertEqual(self.selected(),{a.pk,b.pk})

    def test_live_feed_service_lookup_is_no_longer_ambiguous(self):
        from vehicles.management.commands.import_bod_avl import Command
        preferred=self.service(self.bods)
        self.service(self.passenger)
        command=Command()
        command.services=Service.objects.filter(current=True)
        item={"MonitoredVehicleJourney":{"OperatorRef":"SVCT","LineRef":"1","DestinationRef":"238000000000"}}
        self.assertEqual(command.get_service([self.operator],item,"1","SVCT"),preferred)
