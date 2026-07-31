from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, re_path
from django.views.decorators.cache import cache_control
from django.views.generic.base import RedirectView, TemplateView

from buses.utils import cdn_cache_control
from bustimes.urls import urlpatterns as bustimes_urls
from fares import mytrip
from fares import views as fares_views
from fares.urls import urlpatterns as fares_urls
from fleet import views as fleet_views
from vehicles.urls import urlpatterns as vehicles_urls

# Import disruptions URLs defensively
try:
    from disruptions.urls import urlpatterns as disruptions_urls
except (ImportError, ProgrammingError):
    disruptions_urls = []

from . import views

sitemaps = {
    "operators": views.OperatorSitemap,
    "services": views.ServiceSitemap,
    "vehicles": views.VehicleSitemap,
}

urlpatterns = [
    path("", views.index, name="index"),
    path("blog", views.blog_index, name="blog_index"),
    path("blog/manage", views.blog_manage, name="blog_manage"),
    path("blog/write", views.blog_post_create, name="blog_post_create"),
    path("blog/tags/<slug:slug>", views.blog_tag_detail, name="blog_tag_detail"),
    path("blog/<slug:slug>/edit", views.blog_post_edit, name="blog_post_edit"),
    path(
        "blog/<slug:slug>",
        views.BlogPostDetailView.as_view(),
        name="blog_post_detail",
    ),
    path("version", views.version),
    path("contact", views.contact, name="contact"),
    path(
        "cookies",
        cdn_cache_control(1800)(TemplateView.as_view(template_name="cookies.html")),
    ),
    path(
        "privacy",
        cdn_cache_control(1800)(TemplateView.as_view(template_name="cookies.html")),
    ),
    path("503", TemplateView.as_view(template_name="503.html")),
    path(
        "data", cdn_cache_control(1800)(TemplateView.as_view(template_name="data.html"))
    ),
    path("status", views.status),
    path("fleet/import", views.fleet_import, name="fleet_import"),
    path("fleet/ts-import", views.ts_import, name="ts_import"),
    path("fleet/completion", fleet_views.fleet_completion, name="fleet_completion"),
    path("fleet/completion/user/<str:username>", fleet_views.public_fleet_completion, name="public_fleet_completion"),
    path("fleet/driving-completion", fleet_views.driving_completion, name="driving_completion"),
    path("fleet/driving-completion/user/<str:username>", fleet_views.public_driving_completion, name="public_driving_completion"),
    path("fleet/transittracker-import", fleet_views.transittracker_import, name="transittracker_import"),
    path("fleet/transittracker-import/run", fleet_views.transittracker_import_run, name="transittracker_import_run"),
    path("fleet/transittracker-import/search", fleet_views.transittracker_user_search, name="transittracker_user_search"),
    path("fleet/transittracker-import/check-username", fleet_views.transittracker_check_username, name="transittracker_check_username"),
    path("fleet/transittracker-import/get-operators", fleet_views.transittracker_get_operators, name="transittracker_get_operators"),
    path("fleet/transittracker-import/preview", fleet_views.transittracker_preview, name="transittracker_preview"),
    path("custom-tracking", fleet_views.live_location_tracking, name="live_location_tracking"),
    path("custom-tracking/simulation", fleet_views.manual_tracking_simulation, name="manual_tracking_simulation"),
    path("custom-tracking/vehicles.json", fleet_views.vehicle_search_json, name="vehicle_search_json"),
    path("custom-tracking.json", fleet_views.live_tracking_json, name="live_tracking_json"),
    path("custom-tracking/swap", fleet_views.swap_vehicle_tracking, name="swap_vehicle_tracking"),
    path("custom-tracking/simulation/create", fleet_views.create_manual_simulation, name="create_manual_simulation"),
    path("custom-tracking/simulation/<int:simulation_id>/update", fleet_views.update_manual_simulation, name="update_manual_simulation"),
    path("custom-tracking/simulation/<int:simulation_id>/calculate-route", fleet_views.calculate_simulation_route, name="calculate_simulation_route"),
    path("fleet/live-tracking", RedirectView.as_view(url='/custom-tracking', permanent=True)),
    path("fleet/live-tracking.json", RedirectView.as_view(url='/custom-tracking.json', permanent=True)),
    path("fleet/live-tracking/swap", RedirectView.as_view(url='/custom-tracking/swap', permanent=True)),
    path("staff/stats", views.staff_stats, name="staff_stats"),
    path("staff/theme-lab", views.theme_lab, name="theme_lab"),
    path("timetable-source-stats.json", views.timetable_source_stats),
    path("stats.json", views.stats),
    path("map", TemplateView.as_view(template_name="map.html"), name="map"),
    path("map/trains", views.train_map, name="train_map"),
    path("trains.json", views.trains_json, name="trains_json"),
    path("stops.json", views.stops_json, name="stops_json"),
    path("stops/<int:z>/<int:x>/<int:y>.pbf", views.stops_mvt),
    path(
        "ads.txt",
        cache_control(max_age=1800)(
            RedirectView.as_view(
                url="https://cdn.adfirst.media/adstxt/bustimes-ads.txt"
            )
        ),
    ),
    path("robots.txt", views.robots_txt),
    path(
        "organisations/<slug:slug>",
        views.OrganisationDetailView.as_view(),
        name="organisation_detail",
    ),
    path(
        "organisations/<slug:slug>/map",
        views.organisation_map,
        name="organisation_map",
    ),
    path(
        "major-operators/<slug:slug>",
        views.OrganisationDetailView.as_view(),
        name="major_operator_detail",
    ),
    path(
        "major-operators/<slug:slug>/map",
        views.organisation_map,
        name="major_operator_map",
    ),
    path(
        "preservation-groups/",
        views.preservation_group_list,
        name="preservation_group_list",
    ),
    path(
        "operators/",
        views.operator_list,
        name="operator_list",
    ),
    path(
        "preservation-groups/<slug:slug>/",
        views.preservation_group_detail,
        name="preservation_group_detail",
    ),
    path(
        "government-authorities/",
        views.government_authority_list,
        name="government_authority_list",
    ),
    path(
        "government-authorities/<slug:slug>/",
        views.government_authority_detail,
        name="government_authority_detail",
    ),
    path(
        "government-authorities/<slug:slug>/vehicles/",
        views.government_authority_vehicles,
        name="government_authority_vehicles",
    ),
    path(
        "government-authorities/<slug:slug>/routes/",
        views.government_authority_routes,
        name="government_authority_routes",
    ),
    path(
        "government-authorities/<slug:slug>/operators/",
        views.government_authority_operators,
        name="government_authority_operators",
    ),
    path(
        "manufactors/<slug:slug>",
        views.ManufacturerDetailView.as_view(),
        name="manufacturer_detail",
    ),
    path("regions/<pk>", views.RegionDetailView.as_view(), name="region_detail"),
    path(
        "admin-areas/<pk>",
        views.AdminAreaDetailView.as_view(),
        name="adminarea_detail",
    ),
    re_path(r"^(admin-)?areas/(?P<pk>\d+)", views.AdminAreaDetailView.as_view()),
    path(
        "districts/<int:pk>",
        views.DistrictDetailView.as_view(),
        name="district_detail",
    ),
    re_path(
        r"^localities/(?P<pk>[ENen][Ss]?[0-9]+)",
        views.LocalityDetailView.as_view(),
    ),
    path(
        "localities/<slug>",
        views.LocalityDetailView.as_view(),
        name="locality_detail",
    ),
    path(
        "stops/<pk>",
        views.StopPointDetailView.as_view(),
        name="stoppoint_detail",
    ),
    path("stops/<pk>/edit", views.edit_stop, name="stoppoint_edit"),
    path("stops/<atco_code>/departures", views.stop_departures),
    path("stations/<pk>", views.StopAreaDetailView.as_view(), name="stoparea_detail"),
    path("stations/<pk>/departures", views.stop_area_departures),
    path(
        "stop-groups/<slug>",
        views.StopGroupDetailView.as_view(),
        name="stopgroup_detail",
    ),
    path("stop-groups/<slug>/departures", views.stop_group_departures),
    path(
        "operators/<slug:slug>/routes",
        views.OperatorDetailView.as_view(),
        name="operator_routes",
    ),
    path(
        "operators/<slug:slug>/vehicles/historical",
        views.operator_historical_vehicles,
        name="operator_historical_vehicles",
    ),
    path(
        "operators/<slug:slug>/vehicles/blocks",
        views.operator_blocks,
        name="operator_blocks",
    ),
    path(
        "operators/<slug:slug>/vehicles",
        views.operator_vehicles,
        name="operator_vehicles",
    ),
    re_path(r"^operators/(?P<pk>[A-Z]+)$", views.OperatorDetailView.as_view()),
    path("operators/<slug>", views.OperatorDetailView.as_view(), name="operator_detail"),
    path("operators/<slug>/tickets", mytrip.operator_tickets, name="operator_tickets"),
    path("operators/<slug>/tickets/<uuid:id>", mytrip.operator_ticket),
    path(
        "services/<int:service_id>.json",
        views.service_map_data,
        name="service_map_data",
    ),
    path(
        "services/<int:service_id>/timetable",
        views.service_timetable,
        name="service_timetable",
    ),
    path("services/<int:service_id>/timetable.csv", views.service_timetable_csv),
    path("services/route-editor", views.route_editor, name="route_editor"),
    path(
        "services/route-editor/search",
        views.route_editor_search,
        name="route_editor_search",
    ),
    path(
        "services/<int:service_id>/route-editor.json",
        views.route_editor_service_data,
        name="route_editor_service_data",
    ),
    path(
        "services/<int:service_id>/route-editor/save",
        views.route_editor_save,
        name="route_editor_save",
    ),
    path(
        "services/<slug:slug>/blocks/<path:block>",
        views.service_block_detail,
        name="service_block_detail",
    ),
    path(
        "services/<slug:slug>/route-notices/<int:pk>",
        views.RouteNoticeDetailView.as_view(),
        name="route_notice_detail",
    ),
    path("services/<slug>", views.ServiceDetailView.as_view(), name="service_detail"),
    path("services/<slug>/fares", fares_views.service_fares),
    path("sitemap.xml", cache_control(max_age=3600)(views.sitemap_xml)),
    path(
        "sitemap-<section>.xml",
        cache_control(max_age=3600)(sitemap),
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
    path("search", views.search, name="search"),
    path("site-map", views.site_map, name="site_map"),
    path(
        ".well-known/change-password",
        RedirectView.as_view(url="/accounts/password_change/"),
    ),
    path("journey", views.journey),
    path("fares/", include(fares_urls)),
    path("", include(vehicles_urls)),
    path("", include(disruptions_urls)),
]



