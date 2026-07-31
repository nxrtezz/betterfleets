MAX_RECENTLY_VIEWED = 8
SESSION_KEY = "recently_viewed"


def record_recently_viewed(request, *, item_type, item_id, title, url, subtitle=""):
    items = request.session.get(SESSION_KEY, [])
    item_id = str(item_id)
    filtered = [
        item
        for item in items
        if not (item.get("type") == item_type and str(item.get("id")) == item_id)
    ]
    filtered.insert(
        0,
        {
            "type": item_type,
            "id": item_id,
            "title": title,
            "url": url,
            "subtitle": subtitle,
        },
    )
    request.session[SESSION_KEY] = filtered[:MAX_RECENTLY_VIEWED]
    request.session.modified = True


def get_recently_viewed(request):
    return request.session.get(SESSION_KEY, [])
