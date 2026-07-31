from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from .models import Favourite, FavouriteType
from busstops.models import Operator, Service
from vehicles.models import Vehicle


@login_required
def add_favourite(request):
    """
    Add a favourite via AJAX or POST.
    
    Supports operators, vehicles, and services. Returns JSON for AJAX requests
    or redirects for regular POST requests.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    
    favourite_type = request.POST.get("type")
    operator_id = request.POST.get("operator_id")
    vehicle_id = request.POST.get("vehicle_id")
    service_id = request.POST.get("service_id")
    notes = request.POST.get("notes", "")
    
    try:
        if favourite_type == FavouriteType.OPERATOR:
            operator = get_object_or_404(Operator, pk=operator_id)
            favourite, created = Favourite.objects.get_or_create(
                user=request.user,
                favourite_type=favourite_type,
                operator=operator,
                defaults={"notes": notes}
            )
            if created:
                messages.success(request, f"Added {operator} to favourites.")
            else:
                messages.info(request, f"{operator} is already in your favourites.")
        
        elif favourite_type == FavouriteType.VEHICLE:
            vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
            favourite, created = Favourite.objects.get_or_create(
                user=request.user,
                favourite_type=favourite_type,
                vehicle=vehicle,
                defaults={"notes": notes}
            )
            if created:
                messages.success(request, f"Added {vehicle} to favourites.")
            else:
                messages.info(request, f"{vehicle} is already in your favourites.")
        
        elif favourite_type == FavouriteType.SERVICE:
            service = get_object_or_404(Service, pk=service_id)
            favourite, created = Favourite.objects.get_or_create(
                user=request.user,
                favourite_type=favourite_type,
                service=service,
                defaults={"notes": notes}
            )
            if created:
                messages.success(request, f"Added {service} to favourites.")
            else:
                messages.info(request, f"{service} is already in your favourites.")
        
        else:
            return JsonResponse({"error": "Invalid favourite type"}, status=400)
        
        # Return JSON for AJAX requests
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "created": created,
                "favourite_id": favourite.id
            })
        
        # Redirect for regular POST requests
        redirect_url = request.POST.get("next", request.META.get("HTTP_REFERER", "/"))
        return redirect(redirect_url)
    
    except Exception as e:
        messages.error(request, str(e))
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"error": str(e)}, status=400)
        redirect_url = request.POST.get("next", request.META.get("HTTP_REFERER", "/"))
        return redirect(redirect_url)


@login_required
def remove_favourite(request, favourite_id):
    """
    Remove a favourite.
    
    Returns JSON for AJAX requests or redirects for regular requests.
    """
    favourite = get_object_or_404(Favourite, pk=favourite_id, user=request.user)
    favourite.delete()
    messages.success(request, "Removed from favourites.")
    
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"success": True})
    
    redirect_url = request.GET.get("next", request.META.get("HTTP_REFERER", "/"))
    return redirect(redirect_url)


@login_required
def toggle_favourite(request):
    """
    Toggle a favourite (add if not exists, remove if exists).
    
    Supports operators, vehicles, and services. Returns JSON for AJAX requests
    or redirects for regular POST requests.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    
    favourite_type = request.POST.get("type")
    operator_id = request.POST.get("operator_id")
    vehicle_id = request.POST.get("vehicle_id")
    service_id = request.POST.get("service_id")
    
    try:
        favourite = None
        
        if favourite_type == FavouriteType.OPERATOR:
            operator = get_object_or_404(Operator, pk=operator_id)
            favourite = Favourite.objects.filter(
                user=request.user,
                favourite_type=favourite_type,
                operator=operator
            ).first()
            if favourite:
                favourite.delete()
                messages.success(request, f"Removed {operator} from favourites.")
                is_favourited = False
            else:
                favourite = Favourite.objects.create(
                    user=request.user,
                    favourite_type=favourite_type,
                    operator=operator
                )
                messages.success(request, f"Added {operator} to favourites.")
                is_favourited = True
        
        elif favourite_type == FavouriteType.VEHICLE:
            vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
            favourite = Favourite.objects.filter(
                user=request.user,
                favourite_type=favourite_type,
                vehicle=vehicle
            ).first()
            if favourite:
                favourite.delete()
                messages.success(request, f"Removed {vehicle} from favourites.")
                is_favourited = False
            else:
                favourite = Favourite.objects.create(
                    user=request.user,
                    favourite_type=favourite_type,
                    vehicle=vehicle
                )
                messages.success(request, f"Added {vehicle} to favourites.")
                is_favourited = True
        
        elif favourite_type == FavouriteType.SERVICE:
            service = get_object_or_404(Service, pk=service_id)
            favourite = Favourite.objects.filter(
                user=request.user,
                favourite_type=favourite_type,
                service=service
            ).first()
            if favourite:
                favourite.delete()
                messages.success(request, f"Removed {service} from favourites.")
                is_favourited = False
            else:
                favourite = Favourite.objects.create(
                    user=request.user,
                    favourite_type=favourite_type,
                    service=service
                )
                messages.success(request, f"Added {service} to favourites.")
                is_favourited = True
        
        else:
            return JsonResponse({"error": "Invalid favourite type"}, status=400)
        
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({
                "success": True,
                "is_favourited": is_favourited,
                "favourite_id": favourite.id if is_favourited else None
            })
        
        redirect_url = request.POST.get("next", request.META.get("HTTP_REFERER", "/"))
        return redirect(redirect_url)
    
    except Exception as e:
        messages.error(request, str(e))
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"error": str(e)}, status=400)
        redirect_url = request.POST.get("next", request.META.get("HTTP_REFERER", "/"))
        return redirect(redirect_url)
