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
            queryset = queryset.filter(operators__noc__iexact=operator_noc)
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

    @action(detail=False, methods=['get'])
    def permissions(self, request):
        """Check current user's permissions"""
        user = request.user
        if not user.is_authenticated:
            return Response({'overland': False}, status=401)

        from django.contrib.auth.models import Permission
        overland_perm = Permission.objects.filter(
            codename='use_overland',
            content_type__app_label='fleet'
        ).first()

        has_overland = user.has_perm('fleet.use_overland')

        return Response({
            'overland': has_overland,
        })

    @action(detail=False, methods=['post'])
    def start_tracking(self, request):
        """Start a new tracking session"""
        from fleet.models import OverlandSubscription
        from busstops.models import DataSource, StopPoint
        from bustimes.models import Route, Calendar, Trip, StopTime
        from vehicles.models import Vehicle, VehicleJourney
        from django.utils import timezone
        from secrets import token_urlsafe
        import json

        if not request.user.is_authenticated:
            return Response({'error': 'Authentication required'}, status=401)

        if not request.user.has_perm('fleet.use_overland'):
            return Response({'error': 'Permission denied'}, status=403)

        data = request.data
        vehicle_slug = data.get('vehicle_slug')
        destination = data.get('destination')
        route_number = data.get('route_number')
        tracking_date_str = data.get('tracking_date')
        trip_id = data.get('trip_id')
        service_id = data.get('service_id')
        stops_str = data.get('stops')

        if not vehicle_slug:
            return Response({'error': 'Vehicle slug required'}, status=400)

        try:
            vehicle = Vehicle.objects.get(slug=vehicle_slug)
        except Vehicle.DoesNotExist:
            return Response({'error': 'Vehicle not found'}, status=404)

        # Parse tracking date
        if tracking_date_str:
            try:
                tracking_date = timezone.datetime.strptime(tracking_date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({'error': 'Invalid tracking date'}, status=400)
        else:
            tracking_date = timezone.localdate()

        # Get or create Overland data source
        overland_source, _ = DataSource.objects.get_or_create(
            name="Overland",
            defaults={"url": "https://overland.tech"}
        )

        # Handle scheduled trip mode
        scheduled_trip = None
        if trip_id:
            try:
                scheduled_trip = Trip.objects.get(pk=trip_id)
            except Trip.DoesNotExist:
                return Response({'error': 'Trip not found'}, status=404)
        elif service_id:
            # If service_id is provided but no trip_id, get the first trip for that service
            try:
                from busstops.models import Service
                service = Service.objects.get(pk=service_id)
                scheduled_trip = Trip.objects.filter(
                    route__service=service,
                    calendar__start_date__lte=tracking_date,
                    calendar__end_date__gte=tracking_date
                ).first()
                if not scheduled_trip:
                    return Response({'error': 'No trips found for this service on the selected date'}, status=404)
            except Service.DoesNotExist:
                return Response({'error': 'Service not found'}, status=404)

        # Handle stops for unscheduled mode
        stop_rows = []
        if stops_str:
            try:
                stops_data = json.loads(stops_str)
                for stop_data in stops_data:
                    stop = StopPoint.objects.get(atco_code=stop_data['stop_id'])
                    stop_rows.append({
                        'stop': stop,
                        'arrival': stop_data.get('arrival'),
                        'departure': stop_data.get('departure'),
                        'sequence': stop_data.get('sequence', 0)
                    })
            except (json.JSONDecodeError, StopPoint.DoesNotExist):
                return Response({'error': 'Invalid stops data'}, status=400)

        # Create scheduled trip data if stops provided
        if stop_rows and not scheduled_trip:
            if destination:
                service = Route.objects.create(
                    source=overland_source,
                    line_name=route_number or "Overland",
                    origin=stop_rows[0]["stop"].get_long_name(),
                    destination=destination or stop_rows[-1]["stop"].get_long_name(),
                    start_date=tracking_date,
                    end_date=tracking_date,
                )
                calendar = Calendar.objects.create(
                    start_date=tracking_date,
                    end_date=tracking_date,
                    summary="Overland tracking",
                    source=overland_source,
                    **{
                        day: tracking_date.weekday() == index
                        for index, day in enumerate(
                            ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
                        )
                    },
                )
                scheduled_trip = Trip.objects.create(
                    route=service,
                    calendar=calendar,
                    vehicle_journey_code=f"overland-{vehicle.slug}-{tracking_date:%Y%m%d}",
                    headsign=destination,
                    start=stop_rows[0]["arrival"],
                    end=stop_rows[-1]["departure"],
                    operator=vehicle.operator,
                )
                StopTime.objects.bulk_create([
                    StopTime(
                        trip=scheduled_trip,
                        stop=row["stop"],
                        display_name=row["stop"].get_long_name(),
                        arrival=row["arrival"],
                        departure=row["departure"],
                        sequence=row["sequence"],
                    )
                    for row in stop_rows
                ])

        # Create journey
        if scheduled_trip:
            journey_datetime = scheduled_trip.start_datetime(tracking_date)
            journey_destination = destination or scheduled_trip.headsign or ""
            journey_route = scheduled_trip.route.line_name
            journey_code = scheduled_trip.vehicle_journey_code or route_number
            journey_service = scheduled_trip.route.service
            journey_direction = "inbound" if scheduled_trip.inbound else ""
        else:
            journey_datetime = timezone.make_aware(
                timezone.datetime.combine(tracking_date, timezone.datetime.min.time())
            )
            journey_destination = destination
            journey_route = route_number or "Overland"
            journey_code = route_number or f"overland-{vehicle.slug}"
            journey_service = None
            journey_direction = ""

        journey = VehicleJourney.objects.create(
            vehicle=vehicle,
            datetime=journey_datetime,
            date=tracking_date,
            destination=journey_destination,
            code=journey_code,
            route_name=journey_route,
            source=overland_source,
            direction=journey_direction,
            trip=scheduled_trip,
            service=journey_service,
        )

        # Create subscription
        auth_key = token_urlsafe(32)
        subscription = OverlandSubscription.objects.create(
            user=request.user,
            vehicle=vehicle,
            destination=destination,
            route_number=route_number,
            trip_id=str(scheduled_trip.pk) if scheduled_trip else trip_id,
            scheduled_trip=scheduled_trip,
            tracking_date=tracking_date,
            journey=journey,
            auth_key_hash=OverlandSubscription.hash_auth_key(auth_key),
        )

        return Response({
            'subscription_id': str(subscription.uuid),
            'journey_id': journey.pk,
            'auth_key': auth_key,
        })
