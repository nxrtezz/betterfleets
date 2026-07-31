from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

from .models import ServiceLog
from busstops.models import Service


@login_required
def log_service(request):
    """
    Log a service as ridden or photographed.
    
    Creates or updates a ServiceLog entry for the authenticated user.
    Returns JSON for AJAX requests or redirects for regular POST requests.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    
    service_id = request.POST.get("service_id")
    ridden = request.POST.get("ridden") == "true"
    photographed = request.POST.get("photographed") == "true"
    notes = request.POST.get("notes", "")
    
    service = get_object_or_404(Service, pk=service_id)
    
    log, created = ServiceLog.objects.get_or_create(
        user=request.user,
        service=service,
        defaults={
            "ridden": ridden,
            "photographed": photographed,
            "notes": notes
        }
    )
    
    if not created:
        # Update existing log
        log.ridden = ridden
        log.photographed = photographed
        if notes:
            log.notes = notes
        log.save()
    
    messages.success(request, f"Updated log for {service}.")
    
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "ridden": log.ridden,
            "photographed": log.photographed
        })
    
    redirect_url = request.POST.get("next", request.META.get("HTTP_REFERER", "/"))
    return redirect(redirect_url)


@login_required
def toggle_service_ridden(request, service_id):
    """
    Toggle ridden status for a service.
    
    Creates or updates a ServiceLog entry with ridden status toggled.
    Returns JSON for AJAX requests or redirects for regular requests.
    """
    service = get_object_or_404(Service, pk=service_id)
    log, created = ServiceLog.objects.get_or_create(
        user=request.user,
        service=service,
        defaults={"ridden": True}
    )
    
    if not created:
        log.ridden = not log.ridden
        log.save()
    
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "ridden": log.ridden
        })
    
    redirect_url = request.GET.get("next", request.META.get("HTTP_REFERER", "/"))
    return redirect(redirect_url)


@login_required
def toggle_service_photographed(request, service_id):
    """
    Toggle photographed status for a service.
    
    Creates or updates a ServiceLog entry with photographed status toggled.
    Returns JSON for AJAX requests or redirects for regular requests.
    """
    service = get_object_or_404(Service, pk=service_id)
    log, created = ServiceLog.objects.get_or_create(
        user=request.user,
        service=service,
        defaults={"photographed": True}
    )
    
    if not created:
        log.photographed = not log.photographed
        log.save()
    
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "photographed": log.photographed
        })
    
    redirect_url = request.GET.get("next", request.META.get("HTTP_REFERER", "/"))
    return redirect(redirect_url)
