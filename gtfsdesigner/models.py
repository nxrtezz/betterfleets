from django.db import models
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import Point
from busstops.models import Operator, StopPoint


class GTFSProject(models.Model):
    """A GTFS project containing operators, services, and timetables"""
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('accounts.User', models.CASCADE)

    def __str__(self):
        return self.name


class GTFSOperator(models.Model):
    """GTFS operator (agency)"""
    project = models.ForeignKey(GTFSProject, models.CASCADE, related_name='operators')
    name = models.CharField(max_length=255, help_text="Full name of the operator")
    noc = models.CharField(max_length=10, help_text="National Operator Code")
    url = models.URLField(blank=True, help_text="Operator website URL")
    timezone = models.CharField(max_length=50, default="Europe/London")
    lang = models.CharField(max_length=10, blank=True, default="en")
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    fare_url = models.URLField(blank=True, help_text="URL for fare information")

    def __str__(self):
        return f"{self.name} ({self.noc})"


class GTFSRoute(models.Model):
    """GTFS route"""
    project = models.ForeignKey(GTFSProject, models.CASCADE, related_name='routes')
    operator = models.ForeignKey(GTFSOperator, models.CASCADE, related_name='routes')
    route_id = models.CharField(max_length=255, unique=True)
    agency_id = models.CharField(max_length=255, blank=True)
    route_short_name = models.CharField(max_length=50, help_text="Service number (e.g., '21')")
    route_long_name = models.CharField(max_length=255, blank=True, help_text="Service description")
    route_desc = models.CharField(max_length=255, blank=True)
    route_type = models.IntegerField(default=3, help_text="3 for bus")
    route_url = models.URLField(blank=True)
    route_color = models.CharField(max_length=6, blank=True, help_text="Hex color code")
    route_text_color = models.CharField(max_length=6, blank=True, default="FFFFFF")
    continuous_pickup = models.IntegerField(null=True, blank=True)
    continuous_drop_off = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.route_short_name} - {self.route_long_name or self.route_desc}"


class GTFSCalendar(models.Model):
    """GTFS calendar for service days"""
    project = models.ForeignKey(GTFSProject, models.CASCADE, related_name='calendars')
    service_id = models.CharField(max_length=255, unique=True)
    monday = models.BooleanField(default=False)
    tuesday = models.BooleanField(default=False)
    wednesday = models.BooleanField(default=False)
    thursday = models.BooleanField(default=False)
    friday = models.BooleanField(default=False)
    saturday = models.BooleanField(default=False)
    sunday = models.BooleanField(default=False)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        days = []
        if self.monday: days.append("Mon")
        if self.tuesday: days.append("Tue")
        if self.wednesday: days.append("Wed")
        if self.thursday: days.append("Thu")
        if self.friday: days.append("Fri")
        if self.saturday: days.append("Sat")
        if self.sunday: days.append("Sun")
        return f"{', '.join(days)} {self.start_date} - {self.end_date or 'ongoing'}"


class GTFSCalendarDate(models.Model):
    """GTFS calendar dates for exceptions"""
    project = models.ForeignKey(GTFSProject, models.CASCADE, related_name='calendar_dates')
    service_id = models.CharField(max_length=255)
    date = models.DateField()
    exception_type = models.IntegerField(
        choices=[(1, 'Service added'), (2, 'Service removed')],
        default=1
    )

    def __str__(self):
        return f"{self.date} - {'Added' if self.exception_type == 1 else 'Removed'}"


class GTFSStop(models.Model):
    """GTFS stop (can be new or reference existing StopPoint)"""
    project = models.ForeignKey(GTFSProject, models.CASCADE, related_name='stops')
    stop_id = models.CharField(max_length=255, unique=True)
    stop_code = models.CharField(max_length=50, blank=True)
    stop_name = models.CharField(max_length=255)
    stop_lat = models.FloatField()
    stop_lon = models.FloatField()
    stop_url = models.URLField(blank=True)
    location_type = models.IntegerField(default=0, help_text="0 for stop, 1 for station")
    parent_station = models.ForeignKey('self', models.SET_NULL, null=True, blank=True)
    stop_timezone = models.CharField(max_length=50, blank=True)
    wheelchair_boarding = models.IntegerField(default=0, help_text="0 unknown, 1 yes, 2 no")
    platform_code = models.CharField(max_length=50, blank=True)

    # Reference to existing StopPoint if selected from database
    existing_stop = models.ForeignKey(StopPoint, models.SET_NULL, null=True, blank=True, related_name='gtfs_stops')

    def __str__(self):
        return f"{self.stop_name} ({self.stop_id})"


class RouteStop(models.Model):
    """Link between a route and a stop with direction and sequence"""
    route = models.ForeignKey(GTFSRoute, models.CASCADE, related_name='route_stops')
    stop = models.ForeignKey(GTFSStop, models.CASCADE, related_name='route_stops')
    direction = models.IntegerField(
        choices=[(0, 'Outbound'), (1, 'Inbound')],
        help_text="0 for outbound, 1 for inbound"
    )
    sequence = models.IntegerField(help_text="Order of stops in the route")

    class Meta:
        unique_together = ['route', 'direction', 'sequence']
        ordering = ['direction', 'sequence']

    def __str__(self):
        return f"{self.route} - {self.stop} ({'Inbound' if self.direction == 1 else 'Outbound'} #{self.sequence})"


class GFSTripStop(models.Model):
    """Intermediate model for trip stops with timing point and pickup/dropoff settings"""
    trip = models.ForeignKey('GFSTrip', models.CASCADE, related_name='trip_stops')
    stop = models.ForeignKey(GTFSStop, models.CASCADE)
    sequence = models.IntegerField()
    is_timing_point = models.BooleanField(default=False, help_text="This is a timing point")
    pickup_type = models.IntegerField(default=0, help_text="0 regular, 1 no pickup, 2 must phone, 3 coordinate")
    drop_off_type = models.IntegerField(default=0, help_text="0 regular, 1 no drop off, 2 must phone, 3 coordinate")
    timepoint = models.IntegerField(default=1, help_text="0 approximate, 1 exact")

    class Meta:
        ordering = ['sequence']
        unique_together = ['trip', 'sequence']

    def __str__(self):
        return f"{self.trip} - {self.stop} (seq {self.sequence})"


class GFSTrip(models.Model):
    """GTFS trip"""
    project = models.ForeignKey(GTFSProject, models.CASCADE, related_name='trips')
    route = models.ForeignKey(GTFSRoute, models.CASCADE, related_name='trips')
    service_id = models.CharField(max_length=255)
    trip_id = models.CharField(max_length=255, unique=True)
    trip_headsign = models.CharField(max_length=255, help_text="Destination shown to riders")
    trip_short_name = models.CharField(max_length=50, blank=True)
    direction_id = models.IntegerField(
        choices=[(0, 'Outbound'), (1, 'Inbound')],
        null=True, blank=True
    )
    block_id = models.CharField(max_length=50, blank=True)
    shape_id = models.CharField(max_length=255, blank=True)
    wheelchair_accessible = models.IntegerField(default=0, help_text="0 unknown, 1 yes, 2 no")
    bikes_allowed = models.IntegerField(default=0, help_text="0 unknown, 1 yes, 2 no")

    # Stops relationship through GFSTripStop
    stops = models.ManyToManyField(GTFSStop, through=GFSTripStop)

    def __str__(self):
        return f"{self.trip_id} - {self.trip_headsign}"


class GFSTripTiming(models.Model):
    """Timing information for each stop in a trip"""
    trip_stop = models.ForeignKey(GFSTripStop, models.CASCADE, related_name='timings')
    arrival_time = models.TimeField(null=True, blank=True)
    departure_time = models.TimeField(null=True, blank=True)
    stop_headsign = models.CharField(max_length=255, blank=True)
    pickup_type = models.IntegerField(default=0)
    drop_off_type = models.IntegerField(default=0)
    shape_dist_traveled = models.FloatField(null=True, blank=True)
    timepoint = models.IntegerField(default=1)

    class Meta:
        unique_together = ['trip_stop']

    def __str__(self):
        return f"{self.trip_stop} - {self.arrival_time or 'N/A'}"
