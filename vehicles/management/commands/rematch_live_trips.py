"""Retry BODS trip matches immediately after a timetable repair."""
import json
from collections import Counter
from django.core.management.base import BaseCommand
from django.db import transaction
from busstops.models import DataSource
from bustimes.utils import cache_routes
from vehicles.coverage import live_vehicle_payloads
from vehicles.models import Vehicle
from vehicles.management.commands.import_bod_avl import Command as BodCommand


class Command(BaseCommand):
    help = 'Rematch currently live BODS journeys; dry run by default'

    def add_arguments(self, parser):
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--operators',nargs='+')

    def handle(self,*args,**options):
        live=live_vehicle_payloads()
        importer=BodCommand()
        importer.source=DataSource.objects.get(name='BODS AVL')
        stats=Counter()
        vehicles=Vehicle.objects.filter(pk__in=live,latest_journey__source=importer.source,latest_journey__trip__isnull=True).select_related('latest_journey__service')
        if options.get('operators'):
            vehicles=vehicles.filter(operator_id__in=options['operators'])
        with cache_routes():
            for vehicle in vehicles.iterator(chunk_size=100):
                with transaction.atomic():
                    item=vehicle.latest_journey_data
                    if not item or not item.get('MonitoredVehicleJourney'):
                        continue
                    stats['checked']+=1
                    journey=importer.get_journey(item,vehicle)
                    if journey and journey.pk==vehicle.latest_journey_id and journey.trip_id:
                        stats['matched']+=1
                        if options['apply']:
                            journey.save(update_fields=['trip','service','date','destination'])
                    if not options['apply']:
                        transaction.set_rollback(True)
        self.stdout.write(json.dumps({'applied':options['apply'],**stats}))
