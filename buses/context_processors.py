from django.conf import settings


def ad(request):
    path = request.path
    if (
        "/edit" in path
        or path.endswith("/debug")
        or path.startswith("/accounts/")
        or path.startswith("/fares/")
        or path.startswith("/sources/")
        or "/tickets" in path
    ):
        return {"ad": False}

    return {"ad": True}


def map_config(request):
    return {
        "MAP_DEFAULT_STYLE": settings.MAP_DEFAULT_STYLE,
        "MAP_STYLE_URL": settings.MAP_STYLE_URL,
        "MAP_STYLE_DARK_URL": settings.MAP_STYLE_DARK_URL,
        "STADIA_MAPS_API_KEY": settings.STADIA_MAPS_API_KEY,
        "tracking_map_config": {
            "apiUrl": "/vehicles.json",
            "label": "Live vehicles",
        },
    }
