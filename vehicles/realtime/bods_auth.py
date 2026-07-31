from django.conf import settings


def get_bods_request_kwargs(api_key: str | None = None, auth_mode: str | None = None) -> dict:
    api_key = api_key if api_key is not None else settings.BODS_API_KEY
    auth_mode = (auth_mode or settings.BODS_API_AUTH_MODE or "query").lower()
    if auth_mode not in {"query", "header", "both"}:
        auth_mode = "query"

    kwargs: dict = {
        "headers": {
            "Accept": "application/xml, application/zip, text/xml;q=0.9, */*;q=0.1",
            "User-Agent": settings.BODS_API_USER_AGENT,
        }
    }

    if not api_key:
        return kwargs

    if auth_mode in {"query", "both"}:
        kwargs["params"] = {"api_key": api_key}
    if auth_mode in {"header", "both"}:
        kwargs["headers"]["x-api-key"] = api_key
    return kwargs
