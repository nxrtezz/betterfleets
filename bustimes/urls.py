from django.urls import path, re_path

from . import views

urlpatterns = [
    path("services/<slug>/debug", views.ServiceDebugView.as_view()),
    path("sources", views.SourceListView.as_view()),
    path("sources/<int:pk>", views.SourceDetailView.as_view(), name="source_detail"),
    re_path(
        r"^sources/(?P<source>\d+)/routes/(?P<code>.*)",
        views.route_xml,
        name="route_xml",
    ),
    path("stops/<atco_code>/times.json", views.stop_times_json),
    path("stops/<atco_code>/debug", views.stop_debug),
    path("vehicles/tfl/<reg>", views.tfl_vehicle, name="tfl_vehicle"),
    path(
        "trips/vehicle/<slug:slug>/latest",
        views.latest_trip_for_vehicle,
        name="latest_trip_for_vehicle",
    ),
    path("trips/<str:pk>", views.TripDetailView.as_view(), name="trip_detail"),
    path("trips/<str:pk>/block", views.trip_block, name="block_detail"),
    path("trips/<int:trip_id>/snap", views.snap),
    path("journeys/<int:journey_id>/snap", views.snap),
    path("trip_updates", views.trip_updates),
    path("trip_updates/<slug:feed_name>.json", views.trip_updates_json),
    path("simulated-vehicles.json", views.simulated_vehicles_json, name="simulated_vehicles_json"),
    path("simulation", views.simulation_config, name="simulation_config"),
    path("simulation/service-data", views.simulation_service_data, name="simulation_service_data"),
    path("simulation/save-config", views.simulation_save_config, name="simulation_save_config"),
    path(
        "routelinks/<int:pk>",
        views.route_link_view,
        name="routelink_detail",
    ),
    path("timetable/builder", views.timetable_builder, name="timetable_builder"),
    path("timetable/builder/<int:route_id>", views.timetable_builder, name="timetable_builder_route"),
]
