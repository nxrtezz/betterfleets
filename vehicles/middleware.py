import logging
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class UnicodeDecodeErrorMiddleware(MiddlewareMixin):
    """
    Middleware to catch UnicodeDecodeError exceptions and provide a graceful response.
    This handles cases where database contains invalid UTF-8 sequences.
    Only handles cases that aren't already handled by the view layer.
    """
    
    def process_exception(self, request, exception):
        if isinstance(exception, UnicodeDecodeError):
            logger.error(f"UnicodeDecodeError caught by middleware: {exception}")
            
            # Check if this is a requests page - let the view handle it
            if '/requests/' in request.path:
                return None  # Let the view handle it
            
            # If this is an AJAX request, return JSON error
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({
                    'error': 'Encoding error occurred while processing request. Please try again.'
                }, status=500)
            
            # For regular requests, show a user-friendly error page
            from django.shortcuts import render
            from django.contrib import messages
            
            messages.error(
                request, 
                "An encoding error occurred while loading the page. "
                "This may be due to problematic data in the database. "
                "Please contact an administrator if this issue persists."
            )
            
            # Try to redirect to a safe page
            safe_urls = ['/vehicles/', '/requests/', '/']
            referer = request.META.get('HTTP_REFERER', '')
            
            for safe_url in safe_urls:
                if safe_url in referer:
                    from django.shortcuts import redirect
                    return redirect(safe_url)
            
            # Fallback to vehicles page
            from django.shortcuts import redirect
            return redirect('/vehicles/')
        
        return None
