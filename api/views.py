import struct
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import pagination, viewsets
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Q, Count
from django.db.models.functions import Coalesce

from vehicles.time_aware_polyline import encode_time_aware_polyline

from accounts.models import User
from busstops.models import Operator, Service, StopPoint
from bustimes.models import Garage, StopTime, Trip
from bustimes.utils import contiguous_stoptimes_only
from vehicles.models import Livery, Vehicle, VehicleJourney, VehicleType, VehicleRevision
from vehicles.utils import redis_client
from fleet.models import FleetPhotoLog, FleetRideLog
from photos.models import Photo

from sql_util.utils import Exists

from . import filters, serializers, authentication, permissions


class BadException(APIException):
    status_code = 400


class LimitOffsetPagination(pagination.LimitOffsetPagination):
    max_limit = 1000


class CursorPagination(pagination.CursorPagination):
    ordering = "-pk"
    page_size = 100


class CursorPaginationWithSmallerPageSize(CursorPagination):
    page_size = 10


class VehicleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Vehicle.objects.select_related("vehicle_type", "livery", "operator", "garage")
        .annotate(
            special_features=ArrayAgg("features__name", filter=~Q(features=None)),
        )
        .order_by("id")
    )
    serializer_class = serializers.VehicleSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.VehicleFilter
    pagination_class = LimitOffsetPagination
    authentication_classes = [authentication.OptionalAPIKeyAuthentication]
    permission_classes = []

    def get_authenticators(self):
        return [authentication.OptionalAPIKeyAuthentication()]

    def get_permissions(self):
        if self.action in ['log_photo']:
            return [permissions.IsAPIKeyAuthenticated()]
        return []

    @action(detail=False, methods=['post'])
    def log_photo(self, request):
        reg = request.data.get('reg')
        operator_noc = request.data.get('operator_noc')
        quantity = request.data.get('quantity', 1)
        withdrawn = request.data.get('withdrawn')
        preserved = request.data.get('preserved')
        
        if not reg:
            return Response({'error': 'reg is required'}, status=400)
        
        try:
            quantity = int(quantity)
            if quantity < 1:
                return Response({'error': 'quantity must be at least 1'}, status=400)
        except (ValueError, TypeError):
            return Response({'error': 'quantity must be a valid integer'}, status=400)
        
        try:
            queryset = Vehicle.objects.filter(reg__iexact=reg)
            if operator_noc:
                queryset = queryset.filter(operator__noc__iexact=operator_noc)
            if withdrawn is not None:
                queryset = queryset.filter(withdrawn=withdrawn)
            if preserved is not None:
                queryset = queryset.filter(preserved=preserved)
            vehicle = queryset.get()
        except Vehicle.DoesNotExist:
            return Response({'error': 'Vehicle not found'}, status=404)
        except Vehicle.MultipleObjectsReturned:
            return Response({'error': 'Multiple vehicles found with this reg, please specify operator_noc, withdrawn, or preserved'}, status=400)
        
        user = request.user
        if not user.is_authenticated:
            return Response({'error': 'Authentication required'}, status=401)
        
        photo_log, created = FleetPhotoLog.objects.get_or_create(
            user=user,
            vehicle=vehicle
        )
        photo_log.quantity = quantity
        photo_log.save(update_fields=['quantity'])
        
        return Response({
            'status': 'success',
            'vehicle': str(vehicle),
            'quantity': photo_log.quantity,
            'created': created
        })


class LiveryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Livery.objects.order_by("id")
    serializer_class = serializers.LiverySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.LiveryFilter


class VehicleTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = VehicleType.objects.all()
    serializer_class = serializers.VehicleTypeSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.VehicleTypeFilter


class OperatorViewSet(viewsets.ModelViewSet):
    queryset = (
        Operator.objects.order_by("noc")
        .defer("address", "email", "phone", "search_vector")
        .prefetch_related("garage_set")
    )
    serializer_class = serializers.OperatorSerializer
    pagination_class = CursorPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.OperatorFilter
    authentication_classes = [authentication.OptionalAPIKeyAuthentication]
    permission_classes = []

    def get_authenticators(self):
        # Use optional authentication for all operations
        return [authentication.OptionalAPIKeyAuthentication()]

    def get_permissions(self):
        # Only require authentication for write operations
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAPIKeyAuthenticated()]
        return []

    def get_queryset(self):
        # For write operations, don't filter by vehicle existence
        if self.action in ['create', 'update', 'partial_update']:
            return Operator.objects.order_by("noc")
        
        # For read operations, annotate vehicle count (non-withdrawn)
        queryset = super().get_queryset()
        queryset = queryset.annotate(
            vehicle_count=Count('vehicle', filter=Q(vehicle__withdrawn=False))
        )
        return queryset


class GarageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Garage.objects.select_related("operator").order_by("name")
    serializer_class = serializers.GarageSerializer
    pagination_class = CursorPagination
    filter_backends = [DjangoFilterBackend]
    authentication_classes = [authentication.OptionalAPIKeyAuthentication]
    permission_classes = []

    def get_queryset(self):
        queryset = super().get_queryset()
        operator_noc = self.request.query_params.get('operator') or self.request.query_params.get('owner')
        if operator_noc:
            queryset = queryset.filter(operator_id=operator_noc)
        return queryset


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Service.objects.filter(current=True).prefetch_related("operator")
    serializer_class = serializers.ServiceSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.ServiceFilter


class StopViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        StopPoint.objects.order_by("atco_code")
        .select_related("locality")
        .annotate(
            line_names=ArrayAgg(
                "stopusage__line_name",
                filter=Q(stopusage__service__current=True),
                distinct=True,
                default=None,
            )
        )
    )
    serializer_class = serializers.StopSerializer
    pagination_class = CursorPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.StopFilter


class TripViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Trip.objects.select_related("route__service", "operator")
        .prefetch_related("notes")
        .annotate(
            destination_name=Coalesce(
                "headsign", "destination__locality__name", "destination__common_name"
            )
        )
    )
    serializer_class = serializers.TripSerializer
    pagination_class = CursorPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.TripFilter

    @staticmethod
    def get_stops(obj):
        trips = obj.get_trips()
        stops = (
            StopTime.objects.filter(trip__in=trips)
            .select_related("stop__locality")
            .defer(
                "stop__search_vector",
                "stop__locality__search_vector",
                "stop__locality__latlong",
            )
            .order_by("trip__start", "id")
            # .annotate(
            #     call_condition=Subquery(
            #         Call.objects.filter(
            #             stop_time=OuterRef("id"),
            #             journey__trip=OuterRef("trip"),
            #             journey__situation__current=True,
            #         ).values("condition")[:1]
            #     )
            # )
        )
        if obj.notes.all():
            stops = stops.annotate(note_codes=ArrayAgg("notes__code"))
        if len(trips) > 1:
            stops = contiguous_stoptimes_only(stops, obj.id)
        return stops

    def get_object(self):
        obj = super().get_object()
        obj.stops = self.get_stops(obj)
        return obj


class VehicleJourneyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = VehicleJourney.objects.select_related("vehicle")
    serializer_class = serializers.VehicleJourneySerializer
    pagination_class = CursorPaginationWithSmallerPageSize
    filter_backends = [DjangoFilterBackend]
    filterset_class = filters.VehicleJourneyFilter

    def retrieve(self, request, *args, pk, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        extra_data = {}

        if instance.trip:
            instance.trip.stops = TripViewSet.get_stops(instance.trip)
            extra_data["times"] = serializers.TripSerializer().get_times(instance.trip)

        if redis_client:
            locations = redis_client.lrange(instance.get_redis_key(), 0, -1)
            locations = [
                struct.unpack("I 2f ?h ?h", location) for location in locations
            ]
            polyline = encode_time_aware_polyline(
                [[lat, lng, time] for time, lat, lng, _, _, _, _ in locations]
            )
            extra_data["time_aware_polyline"] = polyline

        extra_data["service"] = {
            "id": instance.service_id,
            "slug": instance.service.slug,
        }

        return Response(serializer.data | extra_data)


class SiteInfoViewSet(viewsets.ViewSet):
    def list(self, request):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        data = {
            "services": Service.objects.filter(current=True).count(),
            "operators": Operator.objects.count(),
            "vehicles": Vehicle.objects.count(),
            "users": User.objects.count(),
        }
        serializer = serializers.SiteInfoSerializer(data)
        return Response(serializer.data)


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.annotate(
        approved_edit_count=Count(
            "edited_revisions", filter=Q(edited_revisions__pending=False, edited_revisions__disapproved=False)
        ),
        disapproved_edit_count=Count(
            "edited_revisions", filter=Q(edited_revisions__disapproved=True)
        ),
        pending_edit_count=Count(
            "edited_revisions", filter=Q(edited_revisions__pending=True)
        ),
        photo_count=Count("photo", distinct=True),
        ride_count=Count("fleet_ride_logs", distinct=True),
    )
    serializer_class = serializers.UserSerializer
    pagination_class = CursorPagination
    authentication_classes = [authentication.OptionalAPIKeyAuthentication]
    permission_classes = []

    def get_authenticators(self):
        return [authentication.OptionalAPIKeyAuthentication()]
