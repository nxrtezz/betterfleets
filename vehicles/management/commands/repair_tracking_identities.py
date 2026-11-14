"""Remove invalid feed bindings and restore affected vehicles' latest pointers."""
import json
from pathlib import Path
from collections import Counter
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from busstops.models import DataSource
from vehicles.models import Vehicle, VehicleCode, VehicleJourney
from vehicles.management.commands.import_bod_avl import Command as BodCommand
from vehicles.utils import redis_client


class Command(BaseCommand):
    help = 'Repair cross-operator BODS identities; dry run by default, with a repair manifest'

    def add_arguments(self, parser):
        parser.add_argument('operators', nargs='+')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--prefixes', nargs='+')

    def handle(self, *args, **options):
        command=BodCommand()
        command.source=DataSource.objects.get(name='BODS AVL')
        bad_codes=[]
        for code in VehicleCode.objects.filter(vehicle__operator_id__in=options['operators'],scheme='BODS').select_related('vehicle'):
            prefix=code.code.split(':')[0]
            if options.get('prefixes') and prefix not in options['prefixes']:
                continue
            if not command.vehicle_matches_item(code.vehicle,{'MonitoredVehicleJourney':{'OperatorRef':prefix}}):
                bad_codes.append({'id':code.pk,'code':code.code,'vehicle':code.vehicle_id})
        bad_latest=[]
        for vehicle in Vehicle.objects.filter(operator_id__in=options['operators']).exclude(latest_journey_data__isnull=True).select_related('latest_journey'):
            item=vehicle.latest_journey_data or {}
            prefix=item.get('MonitoredVehicleJourney',{}).get('OperatorRef')
            if not prefix or (options.get('prefixes') and prefix not in options['prefixes']):
                continue
            if not command.vehicle_matches_item(vehicle,item):
                bad_latest.append({'vehicle':vehicle.pk,'operator':vehicle.operator_id,'latest_journey':vehicle.latest_journey_id,'data':item})
        manifest={'created':timezone.now().isoformat(),'codes':bad_codes,'latest':bad_latest,'moved_journeys':[]}
        summary=Counter(codes=len(bad_codes),latest=len(bad_latest))
        if options['apply']:
            path=Path(settings.DATA_DIR)/('tracking-identity-repair-'+timezone.now().strftime('%Y%m%dT%H%M%S')+'.json')
            path.write_text(json.dumps(manifest,default=str))
            with transaction.atomic():
                VehicleCode.objects.filter(pk__in=[row['id'] for row in bad_codes]).delete()
                for row in bad_latest:
                    vehicle=Vehicle.objects.get(pk=row['vehicle'])
                    target,_=command.get_vehicle(row['data'])
                    if target and target.pk!=vehicle.pk:
                        prefix=row['data']['MonitoredVehicleJourney']['OperatorRef']
                        ids=list(VehicleJourney.objects.filter(vehicle=vehicle,source=command.source,service__operator=prefix).exclude(service__operator=vehicle.operator_id).values_list('id',flat=True).distinct())
                        VehicleJourney.objects.filter(pk__in=ids).update(vehicle=target)
                        manifest['moved_journeys'].append({'from':vehicle.pk,'to':target.pk,'ids':ids})
                        summary['journeys']+=len(ids)
                    valid=VehicleJourney.objects.filter(vehicle=vehicle,service__operator=vehicle.operator_id).order_by('-datetime','-id').first()
                    Vehicle.objects.filter(pk=vehicle.pk).update(latest_journey=valid,latest_journey_data=None)
                # Commit only database changes atomically. Cache entries are
                # cleared below and fresh feed observations repopulate them.
            path.write_text(json.dumps(manifest,default=str))
            affected={row['vehicle'] for row in bad_latest}
            for pk in affected:
                redis_client.delete(f'vehicle{pk}')
                redis_client.zrem('vehicle_location_locations',pk)
            for noc in options['operators']:
                if affected:redis_client.srem(f'operator{noc}vehicles',*affected)
        self.stdout.write(json.dumps({'applied':options['apply'],**summary}))
