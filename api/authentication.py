from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from accounts.models import APIKey


class APIKeyAuthentication(authentication.BaseAuthentication):
    """Custom authentication using API keys"""

    def authenticate(self, request):
        api_key = request.headers.get('Authorization') or request.headers.get('X-API-Key')
        
        if not api_key:
            return None
        
        # Remove 'Bearer ' or 'Key ' prefix if present
        if api_key.startswith('Bearer '):
            api_key = api_key[7:]
        elif api_key.startswith('Key '):
            api_key = api_key[4:]
        
        try:
            key_obj = APIKey.objects.select_related('user').get(key=api_key, is_active=True)
        except APIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid API key')
        
        # Update last used timestamp
        from django.utils import timezone
        key_obj.last_used_at = timezone.now()
        key_obj.save(update_fields=['last_used_at'])
        
        return (key_obj.user, None)


class OptionalAPIKeyAuthentication(authentication.BaseAuthentication):
    """Optional authentication using API keys - doesn't fail if no key provided"""

    def authenticate(self, request):
        api_key = request.headers.get('Authorization') or request.headers.get('X-API-Key')
        
        if not api_key:
            return None
        
        # Remove 'Bearer ' or 'Key ' prefix if present
        if api_key.startswith('Bearer '):
            api_key = api_key[7:]
        elif api_key.startswith('Key '):
            api_key = api_key[4:]
        
        try:
            key_obj = APIKey.objects.select_related('user').get(key=api_key, is_active=True)
        except APIKey.DoesNotExist:
            # Return None instead of raising error for optional auth
            return None
        
        # Update last used timestamp
        from django.utils import timezone
        key_obj.last_used_at = timezone.now()
        key_obj.save(update_fields=['last_used_at'])
        
        return (key_obj.user, None)
