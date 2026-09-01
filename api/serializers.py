from rest_framework import serializers

from accounts.models import User
from busstops.models import Operator, Service, StopPoint
from bustimes.models import Garage, Note, Trip
from vehicles.models import Livery, Vehicle, VehicleJourney, VehicleType


class VehicleTypeSerializer(serializers.ModelSerializer):
    vehicle_id = serializers.IntegerField(source="id", read_only=True)
    type = serializers.CharField(source="style", read_only=True)
    coach = serializers.SerializerMethodField()
    electric = serializers.SerializerMethodField()
    double_decker = serializers.SerializerMethodField()

    def get_coach(self, obj) -> bool:
        return obj.style == "coach"

    def get_electric(self, obj) -> bool:
        return obj.fuel == "electric"

    def get_double_decker(self, obj) -> bool:
        return obj.style == "double decker"

    class Meta:
        model = VehicleType
        fields = [
            "id",
            "vehicle_id",
            "external_id",
            "name",
            "style",
            "type",
            "fuel",
            "company",
            "double_decker",
            "coach",
            "electric",
        ]


class VehicleSerializer(serializers.ModelSerializer):
    operator = serializers.SerializerMethodField()
    livery = serializers.SerializerMethodField()
    fleet_num = serializers.IntegerField(source="fleet_number", read_only=True)
    registration = serializers.SerializerMethodField()
    previous_reg = serializers.SerializerMethodField()
    vehicle_type = VehicleTypeSerializer()
    special_features = serializers.ListField()
    status = serializers.SerializerMethodField()

    def get_operator(self, obj):
        if obj.operator_id:
            return {
                "id": obj.operator_id,
                "slug": obj.operator.slug,
                "name": str(obj.operator),
            }

    def get_livery(self, obj):
        if obj.colours or obj.livery_id:
            return {
                "id": obj.livery_id,
                "livery_id": obj.livery_id,
                "name": obj.livery_id and str(obj.livery),
                "left": obj.get_livery(),
                "right": obj.get_livery(90),
            }

    def get_registration(self, obj):
        if obj.vehicle_type and obj.vehicle_type.style == "train" and (obj.fleet_number or obj.fleet_code):
            return ""
        return obj.reg

    def get_previous_reg(self, obj):
        if obj.prev_registration:
            return obj.prev_registration
        return obj.data_get(key="Previous reg")

    def get_status(self, obj):
        return {
            "VOR": obj.vor,
            "Trainer": obj.trainer_vehicle,
            "FleetSupportVehicle": obj.fleet_support_vehicle,
            "AwaitingDelivery": obj.awaiting_delivery,
        }

    class Meta:
        model = Vehicle
        depth = 1
        fields = [
            "id",
            "external_id",
            "slug",
            "fleet_number",
            "fleet_num",
            "fleet_code",
            "reg",
            "registration",
            "prev_registration",
            "previous_reg",
            "vehicle_type",
            "livery",
            "branding",
            "operator",
            "garage",
            "name",
            "notes",
            "engine",
            "gearbox",
            "length",
            "capacity",
            "emissions_rating",
            "chassis",
            "withdrawn",
            "special_features",
            "status",
        ]


class GarageSerializer(serializers.ModelSerializer):
    garage_id = serializers.IntegerField(source="id", read_only=True)
    owner = serializers.CharField(source="operator_id", read_only=True)

    class Meta:
        model = Garage
        fields = [
            "garage_id",
            "external_id",
            "code",
            "name",
            "owner",
            "region_id",
        ]


class OperatorSerializer(serializers.ModelSerializer):
    mode = serializers.CharField(source="vehicle_mode", read_only=True)
    garages = GarageSerializer(many=True, read_only=True)
    vehicle_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Operator
        fields = [
            "noc",
            "external_id",
            "slug",
            "name",
            "slogan",
            "logo",
            "aka",
            "preserved",
            "ceased_operations_on",
            "vehicle_mode",
            "mode",
            "region_id",
            "url",
            "twitter",
            "social_x",
            "social_fb",
            "social_instagram",
            "social_linkedin",
            "social_youtube",
            "social_tiktok",
            "social_threads",
            "social_bluesky",
            "social_mastodon",
            "social_other",
            "garages",
            "vehicle_count",
        ]
        read_only_fields = ["slug"]


class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            "id",
            "slug",
            "service_code",
            "line_name",
            "line_brand",
            "description",
            "region_id",
            "mode",
            "operator",
            "current",
            "tracking",
            "public_use",
            "is_rail_replacement",
            "train_operator",
            "modified_at",
        ]


class StopSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    long_name = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    icon = serializers.SerializerMethodField()
    line_names = serializers.ListField()
    get_name = staticmethod(StopPoint.get_name_for_timetable)
    get_long_name = staticmethod(StopPoint.get_long_name)

    def get_location(self, obj):
        if obj.latlong:
            return obj.latlong.coords

    def get_icon(self, obj):
        return obj.get_icon()

    class Meta:
        model = StopPoint
        fields = [
            "atco_code",
            "naptan_code",
            "common_name",
            "name",
            "long_name",
            "location",
            "indicator",
            "icon",
            "line_names",
            "bearing",
            "heading",
            "stop_type",
            "bus_stop_type",
            "created_at",
            "modified_at",
            "active",
        ]


class LiverySerializer(serializers.ModelSerializer):
    livery_id = serializers.IntegerField(source="id", read_only=True)
    css = serializers.CharField(source="left_css", read_only=True)

    class Meta:
        model = Livery
        fields = [
            "id",
            "livery_id",
            "external_id",
            "name",
            "css",
            "left_css",
            "right_css",
            "white_text",
            "text_colour",
            "stroke_colour",
        ]


class NoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Note
        fields = [
            "code",
            "text",
        ]


class TripSerializer(serializers.ModelSerializer):
    service = serializers.SerializerMethodField()
    operator = serializers.SerializerMethodField()
    times = serializers.SerializerMethodField()
    notes = NoteSerializer(many=True)
    headsign = serializers.CharField(source="destination_name")

    @staticmethod
    def get_service(obj):
        if obj.route:
            return {
                "id": obj.route.service_id,
                "line_name": obj.route.line_name,
                "slug": obj.route.service and obj.route.service.slug,
                "mode": obj.route.service and obj.route.service.mode,
            }

    @staticmethod
    def get_operator(obj):
        if obj.operator:
            return {
                "noc": obj.operator_id,
                "name": str(obj.operator),
                "vehicle_mode": obj.operator.vehicle_mode,
                "slug": obj.operator.slug,
            }

    @staticmethod
    def get_times(obj):
        if not hasattr(obj, "stops"):
            return

        if obj.route and obj.route.service:
            route_links = {
                (link.from_stop_id, link.to_stop_id): link
                for link in obj.route.service.routelink_set.all()
            }
        else:
            route_links = {}
        previous_stop_id = None

        for stop_time in obj.stops:
            route_link = route_links.get((previous_stop_id, stop_time.stop_id))
            if stop := stop_time.stop:
                name = stop_time.display_name or stop.get_name_for_timetable()
                bearing = stop.get_heading()
                location = stop.latlong and stop.latlong.coords
                icon = stop.get_icon()
            else:
                name = stop_time.stop_code
                bearing = None
                location = None
                icon = None
            if hasattr(stop_time, "note_codes"):
                notes = stop_time.note_codes
            else:
                notes = None
            yield {
                "id": stop_time.id,
                "stop": {
                    "atco_code": stop_time.stop_id,
                    "name": name,
                    "location": location,
                    "bearing": bearing,
                    "icon": icon,
                },
                "aimed_arrival_time": stop_time.arrival_time(),
                "aimed_departure_time": stop_time.departure_time(),
                "track": route_link and route_link.geometry.coords,
                "timing_status": stop_time.timing_status,
                "pick_up": stop_time.pick_up,
                "set_down": stop_time.set_down,
                "expected_arrival_time": getattr(stop_time, "expected_arrival", None),
                "expected_departure_time": getattr(
                    stop_time, "expected_departure", None
                ),
                "note_codes": notes,
            }
            previous_stop_id = stop_time.stop_id

    class Meta:
        model = Trip
        fields = [
            "id",
            "vehicle_journey_code",
            "ticket_machine_code",
            "block",
            "start",
            "end",
            "headsign",
            "service",
            "operator",
            "notes",
            "times",
        ]


class VehicleJourneySerializer(serializers.ModelSerializer):
    vehicle = serializers.SerializerMethodField()

    def get_vehicle(self, obj):
        if obj.vehicle_id:
            reg = obj.vehicle.reg
            if obj.vehicle.vehicle_type and obj.vehicle.vehicle_type.style == "train" and (obj.vehicle.fleet_number or obj.vehicle.fleet_code):
                reg = ""
            return {
                "id": obj.vehicle_id,
                "slug": obj.vehicle.slug,
                "fleet_code": obj.vehicle.fleet_code,
                "reg": reg,
            }

    class Meta:
        model = VehicleJourney
        fields = [
            "id",
            "datetime",
            "vehicle",
            "route_name",
            "destination",
            "trip_id",
        ]


class SiteInfoSerializer(serializers.Serializer):
    services = serializers.IntegerField()
    operators = serializers.IntegerField()
    vehicles = serializers.IntegerField()
    users = serializers.IntegerField()


class UserSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField()
    display_name = serializers.CharField()
    trusted = serializers.BooleanField()
    profile_picture = serializers.SerializerMethodField()
    approved_edit_count = serializers.IntegerField()
    disapproved_edit_count = serializers.IntegerField()
    pending_edit_count = serializers.IntegerField()
    badges = serializers.SerializerMethodField()
    photo_count = serializers.IntegerField()
    ride_count = serializers.IntegerField()
    profile_url = serializers.SerializerMethodField()

    def get_profile_picture(self, obj):
        return obj.get_profile_picture_url()

    def get_badges(self, obj):
        return [{"name": tag.name, "slug": tag.slug} for tag in obj.get_profile_tags()]

    def get_profile_url(self, obj):
        return obj.get_absolute_url()

    class Meta:
        model = User
        fields = [
            "id",
            "display_name",
            "trusted",
            "profile_picture",
            "approved_edit_count",
            "disapproved_edit_count",
            "pending_edit_count",
            "badges",
            "photo_count",
            "ride_count",
            "profile_url",
        ]
