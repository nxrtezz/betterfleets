from contextvars import ContextVar


current_request = ContextVar("current_request", default=None)


class CurrentRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            current_request.reset(token)


def get_current_user():
    request = current_request.get()
    if not request:
        return None
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return user
    return None


def is_admin_request():
    request = current_request.get()
    return bool(request and request.path.startswith("/admin/"))
