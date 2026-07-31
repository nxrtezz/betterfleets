from rest_framework import permissions


class IsAPIKeyAuthenticated(permissions.BasePermission):
    """Only allow requests with valid API key authentication"""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
