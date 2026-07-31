from django.db.models import Q
from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from busstops.models import Operator
from vehicles.models import Vehicle

from .serializers import (
    OperatorTimelineSerializer,
    VehicleHistoryEventCreateSerializer,
    VehicleHistoryEventSerializer,
    VehicleTimelineSerializer,
)
from .models import VehicleHistoryEvent


class VehicleHistoryEventFilter(filters.FilterSet):
    event_type = filters.CharFilter(field_name="event_type")
    year = filters.NumberFilter(method="filter_year")
    future_only = filters.BooleanFilter(method="filter_future_only")
    automatic_only = filters.BooleanFilter(field_name="is_automatic")

    def filter_year(self, queryset, name, value):
        if value is not None:
            return queryset.filter(event_date__year=value)
        return queryset

    def filter_future_only(self, queryset, name, value):
        if value:
            return queryset.filter(is_future_event=True)
        return queryset

    class Meta:
        model = VehicleHistoryEvent
        fields = ["event_type", "year", "future_only", "automatic_only"]


class VehicleHistoryEventViewSet(viewsets.ModelViewSet):
    queryset = VehicleHistoryEvent.objects.select_related("vehicle", "created_by").prefetch_related("attachments__photo")
    serializer_class = VehicleHistoryEventSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = VehicleHistoryEventFilter

    def get_serializer_class(self):
        if self.action == "create":
            return VehicleHistoryEventCreateSerializer
        return VehicleHistoryEventSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["get"], url_path="vehicle/(?P<vehicle_id>[^/.]+)/timeline")
    def vehicle_timeline(self, request, vehicle_id=None):
        """Get complete timeline for a specific vehicle."""
        try:
            vehicle = Vehicle.objects.get(id=vehicle_id)
        except Vehicle.DoesNotExist:
            return Response({"error": "Vehicle not found"}, status=404)

        events = self.queryset.filter(vehicle_id=vehicle_id)

        # Apply filters if provided
        event_type = request.query_params.get("event_type")
        if event_type:
            events = events.filter(event_type=event_type)

        year = request.query_params.get("year")
        if year:
            try:
                events = events.filter(event_date__year=int(year))
            except ValueError:
                pass

        future_only = request.query_params.get("future_only")
        if future_only and future_only.lower() in ["true", "1"]:
            events = events.filter(is_future_event=True)

        automatic_only = request.query_params.get("automatic_only")
        if automatic_only and automatic_only.lower() in ["true", "1"]:
            events = events.filter(is_automatic=True)

        serializer = VehicleTimelineSerializer(
            {"vehicle": vehicle, "events": events}
        )
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="operator/(?P<operator_id>[^/.]+)/timeline")
    def operator_timeline(self, request, operator_id=None):
        """Get timeline for all vehicles belonging to an operator."""
        try:
            operator = Operator.objects.get(id=operator_id)
        except Operator.DoesNotExist:
            return Response({"error": "Operator not found"}, status=404)

        # Get all vehicles for this operator
        vehicle_ids = Vehicle.objects.filter(operator_id=operator_id).values_list("id", flat=True)

        # Get all events for these vehicles
        events = self.queryset.filter(vehicle_id__in=vehicle_ids).select_related("vehicle__operator")

        # Apply filters if provided
        event_type = request.query_params.get("event_type")
        if event_type:
            events = events.filter(event_type=event_type)

        year = request.query_params.get("year")
        if year:
            try:
                events = events.filter(event_date__year=int(year))
            except ValueError:
                pass

        vehicle_filter = request.query_params.get("vehicle")
        if vehicle_filter:
            try:
                events = events.filter(vehicle_id=int(vehicle_filter))
            except ValueError:
                pass

        future_only = request.query_params.get("future_only")
        if future_only and future_only.lower() in ["true", "1"]:
            events = events.filter(is_future_event=True)

        automatic_only = request.query_params.get("automatic_only")
        if automatic_only and automatic_only.lower() in ["true", "1"]:
            events = events.filter(is_automatic=True)

        serializer = OperatorTimelineSerializer(
            {"operator": operator, "events": events}
        )
        return Response(serializer.data)
