from rest_framework import serializers

from busstops.models import Operator
from bustimes.models import Garage
from photos.models import Photo
from vehicles.models import Livery, Vehicle

from .models import DatePrecision, EventType, VehicleHistoryAttachment, VehicleHistoryEvent


class VehicleHistoryAttachmentSerializer(serializers.ModelSerializer):
    photo = serializers.SerializerMethodField()

    def get_photo(self, obj):
        if obj.photo:
            return {
                "id": obj.photo.id,
                "url": obj.photo.get_absolute_url() if hasattr(obj.photo, "get_absolute_url") else None,
                "thumbnail": obj.photo.thumbnail.url if hasattr(obj.photo, "thumbnail") and obj.photo.thumbnail else None,
            }

    class Meta:
        model = VehicleHistoryAttachment
        fields = [
            "id",
            "photo",
            "caption",
        ]


class VehicleHistoryEventSerializer(serializers.ModelSerializer):
    vehicle = serializers.SerializerMethodField()
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    date_precision_display = serializers.CharField(source="get_date_precision_display", read_only=True)
    attachments = VehicleHistoryAttachmentSerializer(many=True, read_only=True)
    metadata_resolved = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()

    def get_vehicle(self, obj):
        if obj.vehicle:
            return {
                "id": obj.vehicle.id,
                "slug": obj.vehicle.slug,
                "fleet_code": obj.vehicle.fleet_code,
                "reg": obj.vehicle.reg,
                "name": str(obj.vehicle),
            }

    def get_created_by(self, obj):
        if obj.created_by:
            return {
                "id": obj.created_by.id,
                "username": obj.created_by.username,
            }

    def get_metadata_resolved(self, obj):
        """Resolve referenced entities in metadata to display data."""
        resolved = {}
        metadata = obj.metadata or {}

        # Resolve operator references
        if "from_operator" in metadata:
            try:
                operator = Operator.objects.get(id=metadata["from_operator"])
                resolved["from_operator"] = {"id": operator.id, "name": str(operator), "slug": operator.slug}
            except Operator.DoesNotExist:
                resolved["from_operator"] = {"id": metadata["from_operator"], "name": "Unknown", "deleted": True}

        if "to_operator" in metadata:
            try:
                operator = Operator.objects.get(id=metadata["to_operator"])
                resolved["to_operator"] = {"id": operator.id, "name": str(operator), "slug": operator.slug}
            except Operator.DoesNotExist:
                resolved["to_operator"] = {"id": metadata["to_operator"], "name": "Unknown", "deleted": True}

        # Resolve livery references
        if "from_livery" in metadata:
            try:
                livery = Livery.objects.get(id=metadata["from_livery"])
                resolved["from_livery"] = {"id": livery.id, "name": livery.name}
            except Livery.DoesNotExist:
                resolved["from_livery"] = {"id": metadata["from_livery"], "name": "Unknown", "deleted": True}

        if "to_livery" in metadata:
            try:
                livery = Livery.objects.get(id=metadata["to_livery"])
                resolved["to_livery"] = {"id": livery.id, "name": livery.name}
            except Livery.DoesNotExist:
                resolved["to_livery"] = {"id": metadata["to_livery"], "name": "Unknown", "deleted": True}

        # Resolve garage references
        if "from_garage" in metadata:
            try:
                garage = Garage.objects.get(id=metadata["from_garage"])
                resolved["from_garage"] = {"id": garage.id, "name": garage.name, "code": garage.code}
            except Garage.DoesNotExist:
                resolved["from_garage"] = {"id": metadata["from_garage"], "name": "Unknown", "deleted": True}

        if "to_garage" in metadata:
            try:
                garage = Garage.objects.get(id=metadata["to_garage"])
                resolved["to_garage"] = {"id": garage.id, "name": garage.name, "code": garage.code}
            except Garage.DoesNotExist:
                resolved["to_garage"] = {"id": metadata["to_garage"], "name": "Unknown", "deleted": True}

        # Registration changes are just strings, no resolution needed
        if "from_registration" in metadata:
            resolved["from_registration"] = metadata["from_registration"]
        if "to_registration" in metadata:
            resolved["to_registration"] = metadata["to_registration"]

        return resolved

    class Meta:
        model = VehicleHistoryEvent
        fields = [
            "id",
            "vehicle",
            "event_type",
            "event_type_display",
            "title",
            "description",
            "event_date",
            "date_precision",
            "date_precision_display",
            "is_future_event",
            "is_automatic",
            "created_by",
            "metadata",
            "metadata_resolved",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class VehicleHistoryEventCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleHistoryEvent
        fields = [
            "vehicle",
            "event_type",
            "title",
            "description",
            "event_date",
            "date_precision",
            "is_future_event",
            "metadata",
        ]


class VehicleTimelineSerializer(serializers.Serializer):
    """Serializer for vehicle timeline endpoint."""
    vehicle = serializers.SerializerMethodField()
    events = VehicleHistoryEventSerializer(many=True)

    def get_vehicle(self, obj):
        vehicle = obj["vehicle"]
        return {
            "id": vehicle.id,
            "slug": vehicle.slug,
            "fleet_code": vehicle.fleet_code,
            "reg": vehicle.reg,
            "name": str(vehicle),
            "operator": {
                "id": vehicle.operator.id,
                "name": str(vehicle.operator),
                "slug": vehicle.operator.slug,
            } if vehicle.operator else None,
        }


class OperatorTimelineSerializer(serializers.Serializer):
    """Serializer for operator timeline endpoint."""
    operator = serializers.SerializerMethodField()
    events = VehicleHistoryEventSerializer(many=True)

    def get_operator(self, obj):
        operator = obj["operator"]
        return {
            "id": operator.id,
            "noc": operator.noc,
            "name": str(operator),
            "slug": operator.slug,
        }
