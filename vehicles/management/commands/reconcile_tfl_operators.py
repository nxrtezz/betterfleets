"""Repair contractor attribution using the cached TfL TNDS operator records."""
import json
from collections import defaultdict, Counter
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from busstops.models import Operator, DataSource, Service
from bustimes.models import Route, Trip
from vehicles.models import Vehicle
from vehicles.utils import _merge_duplicate_vehicle, redis_client
from tfl.operators import operator_noc, TFL_OPERATOR_NOCS


class Command(BaseCommand):
    help = 'Reconcile TfL contractors from reviewed TNDS operator evidence; dry run by default'

    def add_arguments(self, parser):
        parser.add_argument('--evidence', required=True, type=Path)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        evidence = json.loads(options['evidence'].read_text())
        assignments = {}
        for filename, operators in evidence.items():
            nocs = {operator_noc(op.get('NationalOperatorCode'), op.get('OperatorCode')) for op in operators}
            if nocs and None not in nocs:
                assignments[filename] = nocs
        from django.db.models import Count
        source = DataSource.objects.filter(name='L').annotate(routes=Count('route')).order_by('-routes','id').first()
        if not source:
            raise CommandError('No London timetable source')
        summary = Counter()
        manifest = {'created': timezone.now().isoformat(), 'routes': [], 'vehicles': []}
        with transaction.atomic():
            for noc, name in [('LOTR','London Transit'), ('NXHH','Hotel Hoppa')]:
                if options['apply']:
                    Operator.objects.get_or_create(noc=noc,defaults={'name': name,'vehicle_mode':'bus'})
            known = set(Operator.objects.values_list('pk',flat=True))
            services = set()
            for route in Route.objects.filter(source=source, service__isnull=False).select_related('service'):
                nocs = assignments.get(route.code)
                if not nocs or not nocs <= known:
                    summary['unresolved_routes'] += 1
                    continue
                services.add(route.service_id)
                before = set(route.service.operator.values_list('pk',flat=True))
                if before != nocs or Trip.objects.filter(route=route).exclude(operator_id__in=nocs).exists():
                    manifest['routes'].append({'id':route.pk,'service':route.service_id,'before':sorted(before),'after':sorted(nocs)})
                    summary['routes'] += 1
                if options['apply'] and len(nocs)==1:
                    Trip.objects.filter(route=route).update(operator_id=next(iter(nocs)))
            # A service can have several route versions; retain their union.
            service_operators = defaultdict(set)
            for route in Route.objects.filter(source=source,service_id__in=services):
                service_operators[route.service_id].update(assignments.get(route.code,set()))
            for pk,nocs in service_operators.items():
                if nocs and nocs <= known and options['apply']:
                    Service.objects.get(pk=pk).operator.set(sorted(nocs))
            for vehicle in Vehicle.objects.filter(operator='TFLO', latest_journey__service_id__in=services).select_related('latest_journey__service').order_by('id'):
                nocs=service_operators[vehicle.latest_journey.service_id] & TFL_OPERATOR_NOCS
                if len(nocs)!=1:
                    continue
                noc=next(iter(nocs))
                collision=Vehicle.objects.filter(operator_id=noc,code=vehicle.code).first()
                if collision and vehicle.reg and collision.reg and vehicle.reg.replace(' ','') != collision.reg.replace(' ',''):
                    summary['conflicting_vehicles']+=1
                    continue
                manifest['vehicles'].append({'id':vehicle.pk,'before':'TFLO','after':noc,'merged_into':collision.pk if collision else None})
                summary['vehicles']+=1
                if options['apply']:
                    if collision:
                        changed=[]
                        _merge_duplicate_vehicle(collision, vehicle, changed)
                        if changed:collision.save(update_fields=changed)
                    else:
                        vehicle.operator_id=noc
                        vehicle.save(update_fields=['operator'])
            if options['apply']:
                manifest_path = Path(settings.DATA_DIR)/'tfl-operator-repair-manifest.json'
                manifest_path.write_text(json.dumps(manifest))
                for row in manifest['vehicles']:
                    redis_client.srem('operatorTFLOvehicles',row['id'])
                    redis_client.delete(f"vehicle{row['id']}")
        self.stdout.write(json.dumps({'applied':options['apply'], **summary},sort_keys=True))
