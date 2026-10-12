from django.contrib import admin
from . import models


@admin.register(models.GTFSProject)
class GTFSProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'created_by']
    list_filter = ['created_at']
    search_fields = ['name']


@admin.register(models.GTFSOperator)
class GTFSOperatorAdmin(admin.ModelAdmin):
    list_display = ['name', 'noc', 'project']
    list_filter = ['project']
    search_fields = ['name', 'noc']


@admin.register(models.GTFSRoute)
class GTFSRouteAdmin(admin.ModelAdmin):
    list_display = ['route_short_name', 'route_long_name', 'operator', 'project']
    list_filter = ['project', 'operator', 'route_type']
    search_fields = ['route_short_name', 'route_long_name', 'route_id']


@admin.register(models.GTFSCalendar)
class GTFSCalendarAdmin(admin.ModelAdmin):
    list_display = ['service_id', 'start_date', 'end_date', 'project']
    list_filter = ['project', 'start_date', 'end_date']
    search_fields = ['service_id']


@admin.register(models.GTFSCalendarDate)
class GTFSCalendarDateAdmin(admin.ModelAdmin):
    list_display = ['service_id', 'date', 'exception_type', 'project']
    list_filter = ['project', 'date', 'exception_type']
    search_fields = ['service_id']


@admin.register(models.GTFSStop)
class GTFSStopAdmin(admin.ModelAdmin):
    list_display = ['stop_name', 'stop_id', 'stop_code', 'project']
    list_filter = ['project', 'location_type']
    search_fields = ['stop_name', 'stop_id', 'stop_code']


@admin.register(models.RouteStop)
class RouteStopAdmin(admin.ModelAdmin):
    list_display = ['route', 'stop', 'direction', 'sequence']
    list_filter = ['route', 'direction']
    search_fields = ['route__route_short_name', 'stop__stop_name']


@admin.register(models.GFSTrip)
class GFSTripAdmin(admin.ModelAdmin):
    list_display = ['trip_id', 'trip_headsign', 'route', 'direction_id', 'project']
    list_filter = ['project', 'route', 'direction_id']
    search_fields = ['trip_id', 'trip_headsign']


@admin.register(models.GFSTripStop)
class GFSTripStopAdmin(admin.ModelAdmin):
    list_display = ['trip', 'stop', 'sequence', 'is_timing_point']
    list_filter = ['is_timing_point', 'pickup_type', 'drop_off_type']


@admin.register(models.GFSTripTiming)
class GFSTripTimingAdmin(admin.ModelAdmin):
    list_display = ['trip_stop', 'arrival_time', 'departure_time']
    list_filter = ['arrival_time', 'departure_time']
