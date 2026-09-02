from django.urls import path
from django.views.generic.base import TemplateView

from . import views
from . import management_views
from fleet import views as fleet_views

urlpatterns = [
    path("dashboard", views.dashboard_home, name="dashboard_home"),
    path("events", views.events, name="events"),
    path("bus-groups/<slug:slug>", views.bus_group_detail, name="bus_group_detail"),
    path("staff/reviews", views.review_moderation, name="review_moderation"),
    path(
        "dashboard/add/<str:app_label>/<str:model_name>",
        views.dashboard_add_model,
        name="dashboard_add_model",
    ),
    path("requests", views.requests_home, name="requests_home"),
    path("requests/report-bug", views.report_bug, name="report_bug"),
    path("requests/generic", views.generic_request_page, name="generic_request_page"),
    # AdditionRequest model was removed - these URL patterns are no longer functional
    # path("requests/hub", management_views.request_hub, name="request_hub"),
    # path("requests/<str:request_type>", management_views.addition_request_page, name="addition_request_page"),
    # path("requests/review", management_views.addition_request_review, name="addition_request_review"),
    path("requests/vehicle", views.request_new_vehicle, name="request_vehicle"),
    path("requests/service", views.request_new_service, name="request_service"),
    path("requests/operator", views.request_new_operator, name="request_operator"),
    path(
        "requests/vehicle-model",
        views.request_new_vehicle_model,
        name="request_vehicle_model",
    ),
    path(
        "requests/<int:log_id>/<action>",
        views.request_log_action,
        name="request_log_action",
    ),
    path(
        "groups/<group_slug>/vehicles", views.operator_vehicles, name="group_vehicles"
    ),
    path(
        "operators/<slug:slug>/vehicles/historical",
        views.operator_vehicles,
        {"historical": True},
        name="operator_historical_vehicles",
    ),
    path(
        "operators/<slug:slug>/fleet-history",
        views.fleet_history_calendar,
        name="fleet_history_calendar",
    ),
    path(
        "operators/<slug:slug>/fleet-history/<int:year>/<int:month>",
        views.fleet_history_month,
        name="fleet_history_month",
    ),
    path(
        "operators/<slug:slug>/vehicles",
        views.operator_vehicles,
        name="operator_vehicles",
    ),
    path(
        "operators/<slug:slug>/vehicles/export/basic",
        views.export_fleet_basic,
        name="operator_vehicles_export_basic",
    ),
    path(
        "operators/<slug:slug>/vehicles/export/advanced",
        views.export_fleet_advanced,
        name="operator_vehicles_export_advanced",
    ),
    path(
        "groups/<group_slug>/vehicles/export/basic",
        views.export_fleet_basic,
        name="group_vehicles_export_basic",
    ),
    path(
        "groups/<group_slug>/vehicles/export/advanced",
        views.export_fleet_advanced,
        name="group_vehicles_export_advanced",
    ),
    path(
        "operators/<slug:slug>/vehicles/clear-logs",
        views.clear_operator_logs,
        name="clear_operator_logs",
    ),
    path(
        "operators/<slug:slug>/vehicles/request-new",
        views.request_new_vehicle,
        name="request_new_vehicle",
    ),
    path("operators/<slug>/map", views.operator_map, name="operator_map"),
    path("operators/<slug:slug>/debug", views.operator_debug),
    path("services/<noc>:<line_name>/vehicles", views.service_vehicles_history),
    path(
        "services/<slug>/vehicles",
        views.service_vehicles_history,
        name="service_vehicles",
    ),
    path("vehicles", views.vehicles),
    path("vehicles/sorn", views.sorn_vehicles, name="sorn_vehicles"),
    path("vehicles/sorn-untaxed", views.operator_sorn_untaxed, name="operator_sorn_untaxed"),
    path("vehicles.json", views.vehicles_json),
    path("vehicles/simple-map-data.json", views.vehicles_json),
    path("vehicles/debug", views.debug),
    path(
        "vehicle-names/<slug:slug>",
        views.VehicleNamePageDetailView.as_view(),
        name="vehicle_name_page_detail",
    ),
    path("vehicles/history", views.vehicle_edits),
    path("vehicles/edits", views.vehicle_edits),
    path(
        "vehicles/revisions/<int:revision_id>/<action>",
        views.vehicle_revision_action,
        name="vehicle_revision_action",
    ),
    path("vehicles/<int:pk>", views.VehicleDetailView.as_view()),
    path(
        "vehicles/<slug:slug>", views.VehicleDetailView.as_view(), name="vehicle_detail"
    ),
    path(
        "vehicles/<int:id>/advanced-edit",
        views.edit_vehicle,
        {"advanced_mode": True},
    ),
    path(
        "vehicles/<slug>/advanced-edit",
        views.edit_vehicle,
        {"advanced_mode": True},
        name="vehicle_advanced_edit",
    ),
    path("vehicles/<int:id>/edit", views.edit_vehicle),
    path("vehicles/<slug>/edit", views.edit_vehicle, name="vehicle_edit"),
    path("vehicles/<int:id>/compare", views.vehicle_compare, name="vehicle_compare"),
    path(
        "vehicles/<int:id>/debug",
        views.latest_journey_debug,
        name="latest_journey_debug",
    ),
    path("vehicles/<slug>/debug", views.latest_journey_debug),
    path("journeys/<int:pk>", views.VehicleJourneyDetailView.as_view()),
    path("journeys/<int:pk>.json", views.journey_json),
    path(
        "vehicles/<int:vehicle_id>/journeys/<int:pk>.json",
        views.journey_json,
        name="vehicle_journey",
    ),
    path(
        "services/<int:service_id>/journeys/<int:pk>.json",
        views.journey_json,
        name="service_journey",
    ),
    path("liveries.<int:version>.css", views.liveries_css),
    path("rules", TemplateView.as_view(template_name="rules.html")),
    path("map", TemplateView.as_view(template_name="map.html"), name="map"),
    path("maps", views.get_redirect_view("map", permanent=True)),
    path("map/old", TemplateView.as_view(template_name="map_classic.html")),
    path("siri/<uuid:uuid>", views.siri_post, name="siri_post"),
    path("overland/<uuid:uuid>", views.overland),
    path("operators/pin", fleet_views.toggle_pin_operator, name="toggle_pin_operator"),
]
