import json
import logging
import hmac
import hashlib
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings

from .models import User

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def clerk_webhook(request):
    """
    Handle Clerk webhooks to sync users with Django database.
    Expects a Clerk webhook signature in the 'clerk-webhook-signature' header.
    """
    # Get the webhook signature from headers
    webhook_signature = request.headers.get('clerk-webhook-signature')
    if not webhook_signature:
        logger.error("Missing Clerk webhook signature")
        return HttpResponseBadRequest("Missing signature")

    # Get the signing secret from settings
    webhook_secret = getattr(settings, 'CLERK_WEBHOOK_SIGNING_SECRET', None)
    if not webhook_secret:
        logger.error("CLERK_WEBHOOK_SIGNING_SECRET not configured")
        return HttpResponseBadRequest("Webhook secret not configured")

    # Verify the webhook signature
    try:
        # Clerk uses the format: "t=timestamp,v1=signature"
        # We need to verify the signature
        timestamp, signature = webhook_signature.split(',')
        timestamp = timestamp.split('=')[1]
        signature = signature.split('=')[1]

        # Create the payload string
        payload = f"{timestamp}.{request.body.decode('utf-8')}"
        
        # Compute the expected signature
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Compare signatures
        if not hmac.compare_digest(signature, expected_signature):
            logger.error("Invalid webhook signature")
            return HttpResponseBadRequest("Invalid signature")
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return HttpResponseBadRequest("Signature verification failed")

    # Parse the webhook payload
    try:
        payload = json.loads(request.body)
        event_type = payload.get('type')
        data = payload.get('data', {})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON payload: {e}")
        return HttpResponseBadRequest("Invalid JSON")

    # Handle different event types
    if event_type == 'user.created':
        return handle_user_created(data)
    elif event_type == 'user.updated':
        return handle_user_updated(data)
    elif event_type == 'user.deleted':
        return handle_user_deleted(data)
    else:
        # Acknowledge other event types
        logger.info(f"Received unhandled event type: {event_type}")
        return JsonResponse({'status': 'ok'})


def handle_user_created(data):
    """Create a new Django user when a Clerk user is created."""
    clerk_user_id = data.get('id')
    email_addresses = data.get('email_addresses', [])
    primary_email = None
    
    # Find the primary email
    for email_obj in email_addresses:
        if email_obj.get('verified', False):
            primary_email = email_obj.get('email_address')
            break
    
    if not primary_email and email_addresses:
        primary_email = email_addresses[0].get('email_address')
    
    if not primary_email:
        logger.error(f"No email found for Clerk user {clerk_user_id}")
        return HttpResponseBadRequest("No email in user data")

    first_name = data.get('first_name') or ''
    last_name = data.get('last_name') or ''
    username = primary_email.split('@')[0]

    try:
        # Check if user already exists (by email or clerk_user_id)
        if User.objects.filter(email=primary_email).exists():
            logger.warning(f"User with email {primary_email} already exists, updating clerk_user_id")
            user = User.objects.get(email=primary_email)
            user.clerk_user_id = clerk_user_id
            user.save(update_fields=['clerk_user_id'])
        elif User.objects.filter(clerk_user_id=clerk_user_id).exists():
            logger.info(f"User with clerk_user_id {clerk_user_id} already exists")
            return JsonResponse({'status': 'ok'})
        else:
            # Create new user
            user = User.objects.create_user(
                username=username,
                email=primary_email,
                first_name=first_name,
                last_name=last_name,
                clerk_user_id=clerk_user_id,
            )
            logger.info(f"Created Django user for Clerk user {clerk_user_id}")

        return JsonResponse({'status': 'ok'})
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return HttpResponseBadRequest(f"Error creating user: {e}")


def handle_user_updated(data):
    """Update Django user when Clerk user is updated."""
    clerk_user_id = data.get('id')
    
    try:
        user = User.objects.get(clerk_user_id=clerk_user_id)
        
        # Update email if changed
        email_addresses = data.get('email_addresses', [])
        primary_email = None
        for email_obj in email_addresses:
            if email_obj.get('verified', False):
                primary_email = email_obj.get('email_address')
                break
        if not primary_email and email_addresses:
            primary_email = email_addresses[0].get('email_address')
        
        if primary_email and primary_email != user.email:
            user.email = primary_email
            user.username = primary_email.split('@')[0]
        
        # Update name fields
        user.first_name = data.get('first_name') or ''
        user.last_name = data.get('last_name') or ''
        
        user.save()
        logger.info(f"Updated Django user for Clerk user {clerk_user_id}")
        return JsonResponse({'status': 'ok'})
    except User.DoesNotExist:
        logger.warning(f"User with clerk_user_id {clerk_user_id} not found for update")
        return JsonResponse({'status': 'ok'})  # Don't fail on update for non-existent users
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return HttpResponseBadRequest(f"Error updating user: {e}")


def handle_user_deleted(data):
    """Deactivate or delete Django user when Clerk user is deleted."""
    clerk_user_id = data.get('id')
    
    try:
        user = User.objects.get(clerk_user_id=clerk_user_id)
        # Deactivate instead of deleting to preserve data
        user.is_active = False
        user.save()
        logger.info(f"Deactivated Django user for deleted Clerk user {clerk_user_id}")
        return JsonResponse({'status': 'ok'})
    except User.DoesNotExist:
        logger.warning(f"User with clerk_user_id {clerk_user_id} not found for deletion")
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return HttpResponseBadRequest(f"Error deleting user: {e}")
