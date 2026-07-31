import folium
from django.contrib.gis.geos import Polygon
from django.db.models import Count
from ciso8601 import parse_datetime
from django.utils.timezone import make_aware


THEME_FIELDS = (
    "header_background",
    "header_foreground",
    "accent_colour",
    "card_background",
    "button_background",
    "button_foreground",
    "custom_css",
)


def get_bounding_box(request):
    return Polygon.from_bbox(
        [request.GET[key] for key in ("xmin", "ymin", "xmax", "ymax")]
    )


def get_datetime(string):
    """return a timezone-aware datetime object
    from a string like 2021-07-05T12:01:57
    (the value of a CreationDateTime or ModificationDateTime attribute)
    """

    if string:
        datetime = parse_datetime(string)
        if not datetime.tzinfo:
            return make_aware(datetime)
        return datetime


def has_theme_settings(obj):
    if not obj:
        return False
    return any(getattr(obj, field, "") for field in THEME_FIELDS if hasattr(obj, field))


def get_theme_source(*candidates):
    fallback = None
    for candidate in candidates:
        if not candidate:
            continue
        fallback = fallback or candidate
        if has_theme_settings(candidate):
            return candidate
    return fallback


def get_operator_social_links(operator):
    return [
        ("Website", operator.url),
        ("X", operator.social_x),
        ("Facebook", operator.social_fb),
        ("Instagram", operator.social_instagram),
        ("LinkedIn", operator.social_linkedin),
        ("YouTube", operator.social_youtube),
        ("TikTok", operator.social_tiktok),
        ("Threads", operator.social_threads),
        ("Bluesky", operator.social_bluesky),
        ("Mastodon", operator.social_mastodon),
        ("More", operator.social_other),
    ]


def _depot_coordinates(location):
    if not location:
        return None
    return list(location.coords)


def _normalise_depot_text(value):
    return " ".join((value or "").split()).casefold()


def _depot_signature(depot):
    coordinates = depot.get("coordinates")
    rounded_coordinates = (
        round(coordinates[0], 6),
        round(coordinates[1], 6),
    ) if coordinates else None
    return (
        rounded_coordinates,
        _normalise_depot_text(depot.get("name")),
        _normalise_depot_text(depot.get("address")),
        _normalise_depot_text(depot.get("notes")),
        depot.get("operator_url", ""),
        depot.get("group_url", ""),
    )


def _dedupe_depots(depots):
    unique_depots = []
    seen = set()
    for depot in depots:
        signature = _depot_signature(depot)
        if signature in seen:
            continue
        seen.add(signature)
        unique_depots.append(depot)
    return unique_depots


def get_operator_depots(operator):
    from bustimes.models import Garage

    depots = Garage.objects.filter(operators=operator).order_by("name", "code")
    if not depots.exists():
        depots = getattr(operator, "ordered_depots", None)
    if depots is None:
        depots = operator.depot_set.order_by("name")
    if hasattr(depots, "model") and depots.model is Garage:
        depots = depots.annotate(vehicle_count=Count("vehicle"))
    group = getattr(operator, "group", None)
    results = []
    for depot in depots:
        results.append(
            {
                "id": depot.pk,
                "name": depot.name or depot.code,
                "address": getattr(depot, "address", ""),
                "notes": "",
                "coordinates": _depot_coordinates(depot.location),
                "operator_name": str(operator),
                "operator_url": operator.get_absolute_url(),
                "filter_url": f"{operator.get_vehicles_url()}?garage={depot.pk}",
                "vehicle_count": getattr(depot, "vehicle_count", None),
                "group_name": group and str(group) or "",
                "group_url": group and group.get_absolute_url() or "",
            }
        )
    return _dedupe_depots(results)


def get_group_depots(group):
    operators = getattr(group, "ordered_operators", None)
    if operators is None:
        operators = group.operator_set.order_by("name")

    depots = []
    for operator in operators:
        depots.extend(get_operator_depots(operator))
    return depots


def get_organisation_depots(groups, operators=()):
    depots = []
    for group in groups:
        depots.extend(get_group_depots(group))
    for operator in operators:
        depots.extend(get_operator_depots(operator))
    return depots


def get_manufacturer_sites(manufacturer):
    results = []
    for site in manufacturer.sites.all():
        notes = site.get_site_type_display().capitalize()
        if site.notes:
            notes = f"{notes}. {site.notes}"
        results.append(
            {
                "name": site.name,
                "address": site.address,
                "notes": notes,
                "coordinates": _depot_coordinates(site.location),
            }
        )
    return _dedupe_depots(results)


def serialize_depot_map_points(depots):
    deduped = {}

    for depot in depots:
        coordinates = depot.get("coordinates")
        if not coordinates:
            continue

        key = (
            round(coordinates[0], 6),
            round(coordinates[1], 6),
            _normalise_depot_text(depot.get("name")),
            _normalise_depot_text(depot.get("address")),
        )
        point = deduped.setdefault(
            key,
            {
                "name": depot["name"],
                "address": depot["address"],
                "notes": depot["notes"],
                "coordinates": coordinates,
                "operator_name": depot.get("operator_name", ""),
                "operator_url": depot.get("operator_url", ""),
                "group_name": depot.get("group_name", ""),
                "group_url": depot.get("group_url", ""),
                "_operator_names": set(),
                "_group_names": set(),
            },
        )

        operator_name = depot.get("operator_name", "")
        if operator_name:
            point["_operator_names"].add(operator_name)
        group_name = depot.get("group_name", "")
        if group_name:
            point["_group_names"].add(group_name)

        if not point["notes"] and depot.get("notes"):
            point["notes"] = depot["notes"]
        if not point["operator_url"] and depot.get("operator_url"):
            point["operator_url"] = depot["operator_url"]
        if not point["group_url"] and depot.get("group_url"):
            point["group_url"] = depot["group_url"]

    points = []
    for point in deduped.values():
        operator_names = sorted(point.pop("_operator_names"))
        group_names = sorted(point.pop("_group_names"))

        if operator_names:
            point["operator_name"] = ", ".join(operator_names)
            if len(operator_names) > 1:
                point["operator_url"] = ""
        if group_names:
            point["group_name"] = ", ".join(group_names)
            if len(group_names) > 1:
                point["group_url"] = ""

        points.append(point)

    return points


def build_depot_map_html(points):
    if not points:
        return ""

    if len(points) == 1:
        depot_map = folium.Map(
            location=[points[0]["coordinates"][1], points[0]["coordinates"][0]],
            zoom_start=10,
            width="100%",
            height=420,
        )
    else:
        depot_map = folium.Map(
            location=[54, -2.9],
            zoom_start=5,
            width="100%",
            height=420,
        )

    bounds = []
    for point in points:
        lat = point["coordinates"][1]
        lon = point["coordinates"][0]
        popup = [f"<strong>{point['name']}</strong>"]
        if point.get("operator_name"):
            popup.append(point["operator_name"])
        if point.get("group_name"):
            popup.append(point["group_name"])
        if point.get("address"):
            popup.append(point["address"])
        if point.get("notes"):
            popup.append(point["notes"])

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup("<br>".join(popup), max_width=280),
            tooltip=point["name"],
        ).add_to(depot_map)
        bounds.append([lat, lon])

    if len(bounds) > 1:
        depot_map.fit_bounds(bounds, padding=(24, 24))

    return depot_map._repr_html_()

