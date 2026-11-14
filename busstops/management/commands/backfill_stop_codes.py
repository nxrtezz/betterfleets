"""Restore NaPTAN/SMS aliases for native and source-scoped timetable stops."""
import json
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from busstops.models import StopPoint


class Command(BaseCommand):
    help = 'Fill missing stop SMS codes from a cached official NaPTAN XML file; dry run by default'

    def add_arguments(self,parser):
        parser.add_argument('path',type=Path)
        parser.add_argument('--apply',action='store_true')

    def handle(self,*args,**options):
        missing=defaultdict(list)
        for stop in StopPoint.objects.filter(Q(naptan_code__isnull=True)|Q(naptan_code='')).only('atco_code','naptan_code').iterator():
            missing[stop.pk.rsplit(':',1)[-1].upper()].append(stop)
        updates=[];manifest=[]
        for _,element in ET.iterparse(options['path']):
            element.tag=element.tag.rsplit('}',1)[-1]
            if element.tag=='StopPoint':
                code=(element.findtext('AtcoCode') or '').upper()
                sms=element.findtext('NaptanCode') or element.findtext('PlateCode')
                if sms and code in missing:
                    for stop in missing.pop(code):
                        manifest.append({'id':stop.pk,'before':stop.naptan_code,'after':sms})
                        stop.naptan_code=sms
                        updates.append(stop)
                element.clear()
            elif element.tag=='StopArea':
                element.clear()
        if options['apply']:
            path=Path(settings.DATA_DIR)/('stop-code-repair-'+timezone.now().strftime('%Y%m%dT%H%M%S')+'.json')
            path.write_text(json.dumps(manifest))
            with transaction.atomic():
                StopPoint.objects.bulk_update(updates,['naptan_code'],batch_size=1000)
        self.stdout.write(json.dumps({'applied':options['apply'],'stops':len(updates)}))
