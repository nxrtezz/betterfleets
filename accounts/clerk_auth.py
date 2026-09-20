import logging

import jwt
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from .models import User

logger = logging.getLogger(__name__)


def _get_token(request):
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return authorization[7:].strip()
    return request.COOKIES.get("__session")


def authenticate_clerk_request(request):
    token = _get_token(request)
    if not token or not settings.CLERK_JWT_KEY:
        return None

    decode_options = {"verify_aud": bool(settings.CLERK_JWT_AUDIENCE)}
    try:
        claims = jwt.decode(
            token,
            settings.CLERK_JWT_KEY,
            algorithms=["RS256"],
            audience=settings.CLERK_JWT_AUDIENCE or None,
            issuer=settings.CLERK_JWT_ISSUER or None,
            options=decode_options,
        )
    except jwt.PyJWTError:
        logger.info("Rejected invalid Clerk session token", exc_info=True)
        return None

    clerk_user_id = claims.get("sub")
    if not clerk_user_id:
        return None
    return User.objects.filter(clerk_user_id=clerk_user_id, is_active=True).first()


class ClerkAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = authenticate_clerk_request(request)
        if user:
            request.user = user
            request.clerk_user = user
        else:
            request.clerk_user = AnonymousUser()
        return self.get_response(request)
