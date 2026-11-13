"""Restore unambiguous links lost by cross-provider timetable cleanup."""
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from busstops.models import Service
from bustimes.models import Route
from vehicles.models import VehicleJourney
from .import_bod_timetables import get_command

class Command(BaseCommand):
    help = "Restore exact source/service-code/line matches for tracking operators missing timetables"
    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
    def handle(self, *args, **options):
        today = timezone.localdate()
        nocs = set(VehicleJourney.objects.filter(
            datetime__gte=timezone.now()-timedelta(days=2),
            vehicle__operator__isnull=False,
        ).order_by().values_list("vehicle__operator_id", flat=True).distinct())
        covered = set(Service.objects.filter(
            operator__in=nocs, current=True, route__trip__isnull=False,
        ).order_by().values_list("operator", flat=True).distinct())
        missing = nocs-covered
        services = defaultdict(list)
        for service in Service.objects.filter(operator__in=missing).exclude(
            service_code=""
        ).distinct():
            services[(service.source_id, service.service_code, service.line_name)].append(service)
        newer = Route.objects.filter(
            source_id=OuterRef("source_id"), service_code=OuterRef("service_code"),
            line_name=OuterRef("line_name"),
            revision_number_context=OuterRef("revision_number_context"),
            start_date__lte=today, revision_number__gt=OuterRef("revision_number"),
        )
        links = []
        changed = {}
        for route in Route.objects.filter(service=None).active_on(today).filter(
            ~Exists(newer)
        ).exclude(service_code=""):
            matches = services.get((route.source_id, route.service_code, route.line_name), [])
            if len(matches) == 1:
                service = matches[0]
                links.append({"route_id": route.pk, "service_id": service.pk})
                changed[service.pk] = service.current
        self.stdout.write(f"Plan: {len(links)} exact route links, {len(changed)} services; {len(missing)} tracking operators lack coverage")
        if not options["apply"] or not links:
            return
        manifest = settings.DATA_DIR / ("timetable-link-repair-" + timezone.now().strftime("%Y%m%dT%H%M%SZ") + ".json")
        manifest.write_text(json.dumps({"links": links, "previous_service_current": changed}, indent=2))
        with transaction.atomic():
            for item in links:
                Route.objects.filter(pk=item["route_id"], service=None).update(service_id=item["service_id"])
            Service.objects.filter(pk__in=changed).update(current=True)
        # Association repair is committed before potentially expensive derived
        # geometry/search rebuilding; the manifest is the rollback record.
        c = get_command()
        c.service_ids = set(changed)
        c.finish_services()
        self.stdout.write(f"Restored {len(links)} links; rollback manifest {manifest}")
