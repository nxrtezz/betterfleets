import logging
import os
import traceback
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
import requests

logger = logging.getLogger(__name__)


class DiscordErrorNotificationMiddleware(MiddlewareMixin):
    """
    Middleware to send error notifications to Discord when exceptions occur.
    """
    
    def process_exception(self, request, exception):
        # Get the Discord endpoint from environment variables
        discord_endpoint = os.environ.get('DISCORD_BUG_ENDPOINT')
        
        if not discord_endpoint:
            logger.warning("DISCORD_BUG_ENDPOINT not configured, skipping error notification")
            return None
        
        # Only send notifications for 500 errors and specific exceptions
        if not isinstance(exception, Exception):
            return None
        
        # Get request information
        path = request.path
        method = request.method
        user = str(request.user) if hasattr(request, 'user') and request.user.is_authenticated else "Anonymous"
        
        # Get exception details
        exception_type = type(exception).__name__
        exception_message = str(exception)
        stack_trace = traceback.format_exc()
        
        # Create Discord embed
        embed = {
            "title": f"🚨 {exception_type} in {method} {path}",
            "description": f"```\n{exception_message}\n```",
            "color": 16711680,  # Red color
            "fields": [
                {
                    "name": "User",
                    "value": user,
                    "inline": True
                },
                {
                    "name": "Method",
                    "value": method,
                    "inline": True
                },
                {
                    "name": "Path",
                    "value": path,
                    "inline": True
                }
            ],
            "footer": {
                "text": "BetterFleet Error Notification"
            }
        }
        
        # Add stack trace as a field if it's not too long
        if len(stack_trace) < 1000:
            embed["fields"].append({
                "name": "Stack Trace",
                "value": f"```\n{stack_trace}\n```",
                "inline": False
            })
        
        # Send to Discord
        try:
            response = requests.post(
                discord_endpoint,
                json={"embeds": [embed]},
                timeout=5
            )
            if response.status_code != 204:
                logger.error(f"Failed to send Discord notification: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error sending Discord notification: {e}")
        
        return None