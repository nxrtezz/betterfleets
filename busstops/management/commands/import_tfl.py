from time import sleep
from itertools import pairwise

import requests
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand
from shapely.geometry import Point
from shapely import wkt
from shapely.ops import substring

from bustimes.models import RouteLink

from ...models import Service, ServiceCode, Region, Operator


class Command(BaseCommand):
    def assign_operator(self, service, operator_name):
        """Try to find and assign an operator by name"""
        # Try to find operator by name (case-insensitive)
        operator = Operator.objects.filter(name__iexact=operator_name).first()
        if operator:
            service.operator.add(operator)
            print(f"Assigned operator {operator.name} to service {service.slug}")
        else:
            print(f"Could not find operator matching '{operator_name}'")

    def get_stops(self, sequence: dict):

        for stop in sequence["stopPoint"]:
            latlon = Point(stop["lon"], stop["lat"])

            yield stop["id"], latlon

    def do_line(self, line_id, params):
        try:
            service = Service.objects.get(
                line_name__iexact=line_id, region="L", current=1
            )
        except Service.DoesNotExist:
            region = Region.objects.get(id="L")
            service = Service.objects.create(
                line_name=line_id,
                region=region,
                current=True,
                mode="bus",
            )
            print(f"Created service: {service.slug}")
        except Service.MultipleObjectsReturned as e:
            print("⚠️", line_id, e)
            return
        print(service.slug)

        response = self.session.get(
            f"https://api.tfl.gov.uk/Line/{line_id}/Route/Sequence/all",
            params=params,
        )
        if not response.ok:
            print(line_id, response)
            return

        data = response.json()

        # Try to get operator information from the API response
        if len(data.get("orderedLineRoutes", [])) > 0:
            line_route = data["orderedLineRoutes"][0]
            if "operatorName" in line_route:
                operator_name = line_route["operatorName"]
                self.assign_operator(service, operator_name)

        if not service.servicecode_set.filter(scheme="TfL").exists():
            ServiceCode.objects.create(scheme="TfL", service=service, code=line_id)

        if not (
            len(data["orderedLineRoutes"])
            == len(data["lineStrings"])
            == len(data["stopPointSequences"])
        ):
            return

        to_create = {}

        for i, sequence in enumerate(data["stopPointSequences"]):
            line_string = GEOSGeometry(
                f'{{ "type": "MultiLineString", "coordinates": {data["lineStrings"][i]} }}'
            ).simplify()
            line_string = wkt.loads(line_string.wkt)

            if line_string.geom_type != "LineString":
                continue

            for j, (origin, destination) in enumerate(
                pairwise(self.get_stops(sequence))
            ):
                from_stop, from_point = origin
                to_stop, to_point = destination

                from_distance = 0 if j == 0 else line_string.project(from_point)
                to_distance = line_string.project(to_point)

                line_substring = substring(line_string, from_distance, to_distance)

                key = (from_stop, to_stop)

                if line_substring.geom_type != "LineString":
                    print(key, line_substring)
                    continue

                if key not in to_create:
                    to_create[key] = RouteLink(
                        from_stop_id=from_stop,
                        to_stop_id=to_stop,
                        geometry=line_substring.wkt,
                        service=service,
                    )

        RouteLink.objects.bulk_create(
            to_create.values(),
            update_conflicts=True,
            update_fields=["geometry"],
            unique_fields=["service", "from_stop", "to_stop"],
        )

        sleep(1)

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("resume_from", nargs="?", type=str)
        parser.add_argument("--api-key", type=str, help="TfL API key")

    def handle(self, *args, resume_from, api_key, **kwargs):

        self.session = requests.Session()

        params = settings.TFL.copy()
        if api_key:
            params["app_key"] = api_key

        response = self.session.get(
            "https://api.tfl.gov.uk/Line/Mode/bus/Route",
            params=params,
        ).json()

        line_names = [route["id"] for route in response]

        if resume_from:
            resume_from = line_names.index(resume_from)
            line_names = line_names[resume_from:]

        existing_service_codes = ServiceCode.objects.filter(
            scheme="TfL", service__current=1
        )

        service_codes_to_delete = existing_service_codes.exclude(code__in=line_names)
        print(service_codes_to_delete)

        for line_name in line_names:
            self.do_line(line_name, params)
