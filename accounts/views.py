from django.conf import settings
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from sql_util.utils import SubqueryCount

from fleet.completion import get_user_ride_stats, get_user_driving_stats, get_user_photo_stats
from accounts.scoring import get_score_breakdown, get_leaderboard
from vehicles.models import Vehicle, VehicleReview

from . import forms
from .models import DiscordLinkCode
from .notifications import notify_new_user

UserModel = get_user_model()


@login_required
def account_dashboard(request):
    """Account dashboard with profile overview and quick actions."""
    from sql_util.utils import SubqueryCount
    from django.db.models import Count, Q
    
    user = UserModel.objects.annotate(
        total_count=SubqueryCount("vehiclerevision"),
        approved_count=SubqueryCount(
            "vehiclerevision", filter=Q(disapproved=False, pending=False)
        ),
        disapproved_count=SubqueryCount(
            "vehiclerevision", filter=Q(pending=False, disapproved=True)
        ),
        review_count=Count("vehicle_reviews", distinct=True),
    ).get(id=request.user.id)
    
    return render(request, 'account/dashboard.html', {'user': user})


@login_required
def account_profile(request):
    """Profile settings page."""
    user = request.user
    form = forms.UserForm(
        request.POST or None,
        request.FILES or None,
        user=user,
        instance=user,
    )

    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except IntegrityError:
            form.add_error("username", "Username taken")
            user.refresh_from_db()

    return render(request, 'account/profile.html', {'form': form})


@login_required
def account_email(request):
    """Email management page."""
    from allauth.account.utils import send_email_confirmation
    from allauth.account.models import EmailAddress
    
    if request.method == "POST":
        action = request.POST.get('action')
        
        if action == 'add':
            email = request.POST.get('email')
            if email:
                try:
                    EmailAddress.objects.add_email(request, request.user, email, confirm=True)
                except Exception as e:
                    # Handle duplicate email or other errors
                    pass
    
    return render(request, 'account/email.html')


@login_required
def account_password(request):
    """Password change page."""
    return render(request, 'account/password.html')


@login_required
def account_sessions(request):
    """Sessions management page."""
    return render(request, 'account/sessions.html')


def _annotated_users():
    return UserModel.objects.annotate(
        total_count=SubqueryCount("vehiclerevision"),
        review_count=Count("vehicle_reviews", distinct=True),
        linked_operator_count=Count("operatoruser", distinct=True),
    ).prefetch_related("manual_tags")


def discord_link(request):
    if not request.user.is_authenticated:
        return redirect("login")

    # Invalidate any existing unused codes for this user
    DiscordLinkCode.objects.filter(user=request.user, is_used=False).delete()

    # Create a new code
    code = DiscordLinkCode.objects.create(user=request.user)

    return render(request, "discord_link.html", {"code": code.code})


def request_driver_status(request):
    if not request.user.is_authenticated:
        return redirect("login")

    if request.method == "POST":
        # Create a driver status request
        from .models import DriverStatusRequest

        DriverStatusRequest.objects.create(
            user=request.user,
            reason=request.POST.get("reason", "")
        )
        return redirect("user_detail", pk=request.user.pk)

    return render(request, "request_driver_status.html")


def driver_stats(request, pk):
    if not request.user.is_authenticated:
        return redirect("login")

    user = get_object_or_404(UserModel, pk=pk)

    # Only allow users to view their own stats or superusers
    if request.user != user and not request.user.is_superuser:
        raise PermissionDenied

    # Only show stats if user is a driver
    if not user.is_driver:
        return render(request, "driver_stats_not_driver.html", {"user": user})

    from fleet.completion import get_user_driving_stats

    stats = get_user_driving_stats(user)

    return render(request, "driver_stats.html", {"user": user, "stats": stats})


def user_list(request):
    users = _annotated_users()
    query = request.GET.get("q", "").strip()
    if query:
        search_filter = (
            Q(username__icontains=query)
            | Q(display_name__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
        if query.isdigit():
            search_filter |= Q(id=int(query))
        users = users.filter(search_filter)

    current_user = None
    if request.user.is_authenticated:
        current_user = users.filter(id=request.user.id).first()
        if current_user:
            users = users.exclude(id=request.user.id)

    users = users.order_by("-trusted", "-total_count", "display_name", "username", "id")

    paginator = Paginator(users, 50)
    users_page = paginator.get_page(request.GET.get("page"))

    for user in users_page:
        user._review_count = user.review_count

    top_reviewers = list(
        _annotated_users()
        .filter(review_count__gt=0)
        .order_by("-review_count", "-total_count", "display_name", "username", "id")[:5]
    )
    top_editors = list(
        _annotated_users()
        .filter(total_count__gt=0)
        .order_by("-total_count", "-review_count", "display_name", "username", "id")[:5]
    )

    for user in top_reviewers + top_editors:
        user._review_count = user.review_count

    return render(
        request,
        "user_list.html",
        {
            "users": users_page,
            "current_user": current_user,
            "query": query,
            "top_reviewers": top_reviewers,
            "top_editors": top_editors,
        },
    )


def user_detail(request, pk):
    """
    Display user profile with tabs for actions, stats, and liveries.
    
    Shows user information, badges, stats, activity timeline, and livery collection.
    """
    from fleet.models import FleetRideLog, FleetPhotoLog
    from photos.models import Photo
    from vehicles.models import VehicleRevision

    users = UserModel.objects.annotate(
        total_count=SubqueryCount("vehiclerevision"),
        approved_count=SubqueryCount(
            "vehiclerevision", filter=Q(disapproved=False, pending=False)
        ),
        disapproved_count=SubqueryCount(
            "vehiclerevision", filter=Q(pending=False, disapproved=True)
        ),
        pending_count=SubqueryCount(
            "vehiclerevision", filter=Q(pending=True, disapproved=False)
        ),
        review_count=Count("vehicle_reviews", distinct=True),
        reviewed_operator_count=Count(
            "vehicle_reviews__vehicle__operator", distinct=True
        ),
        edits_approved_count=Count("approved", distinct=True),
    )

    user = get_object_or_404(users.prefetch_related("manual_tags", "operatoruser_set__operator"), pk=pk)
    user._review_count = user.review_count
    user._reviewed_operator_count = user.reviewed_operator_count

    # Get timeline items
    revisions = VehicleRevision.objects.filter(user=user).select_related(
        "vehicle", "vehicle__operator"
    ).order_by("-created_at")[:50]
    
    reviews = user.vehicle_reviews.filter(
        status=VehicleReview.Status.PUBLISHED
    ).select_related("vehicle", "vehicle__operator").order_by("-updated_at", "-created_at")[:50]
    
    photos = Photo.objects.filter(user=user).prefetch_related(
        "vehicles", "vehicles__operator"
    ).order_by("-created_at")[:50]
    
    ride_logs = FleetRideLog.objects.filter(user=user).select_related(
        "vehicle", "vehicle__operator"
    ).order_by("-created_at")[:50]
    
    photo_logs = FleetPhotoLog.objects.filter(user=user).select_related(
        "vehicle", "vehicle__operator"
    ).order_by("-created_at")[:50]

    # Combine all timeline items
    timeline_items = []
    for rev in revisions:
        timeline_items.append({
            'type': 'revision',
            'item': rev,
            'created_at': rev.created_at,
        })
    for review in reviews:
        timeline_items.append({
            'type': 'review',
            'item': review,
            'created_at': review.updated_at if review.updated_at > review.created_at else review.created_at,
        })
    for photo in photos:
        timeline_items.append({
            'type': 'photo',
            'item': photo,
            'created_at': photo.created_at,
        })
    for log in ride_logs:
        timeline_items.append({
            'type': 'ride_log',
            'item': log,
            'created_at': log.created_at,
        })
    for photo_log in photo_logs:
        timeline_items.append({
            'type': 'photo_log',
            'item': photo_log,
            'created_at': photo_log.created_at,
        })
    
    # Sort by date
    timeline_items.sort(key=lambda x: x['created_at'], reverse=True)
    timeline_items = timeline_items[:100]

    context = {
        "object": user,
        "timeline_items": timeline_items,
        "preserved_vehicles": Vehicle.objects.filter(preserved_by_user=user)
        .select_related("operator", "vehicle_type")
        .order_by("operator__name", "fleet_number", "fleet_code", "reg", "code"),
    }
    can_view_ride_stats = request.user.is_authenticated and (
        request.user == user or request.user.is_superuser or user.fleet_logging_public
    )
    if can_view_ride_stats:
        context["ride_stats"] = get_user_ride_stats(user)
    
    can_view_driving_stats = request.user.is_authenticated and (
        request.user == user or request.user.is_superuser or user.driving_logging_public
    )
    if can_view_driving_stats and user.is_driver:
        context["driving_stats"] = get_user_driving_stats(user)
    
    can_view_photo_stats = request.user.is_authenticated and (
        request.user == user or request.user.is_superuser or user.fleet_logging_public
    )
    if can_view_photo_stats:
        context["photo_stats"] = get_user_photo_stats(user)
    
    # Add score breakdown
    context["score_breakdown"] = get_score_breakdown(user)

    if request.user == user:
        delete_form = forms.DeleteForm()
        form = forms.UserForm(
            request.POST or None,
            request.FILES or None,
            user=user,
            instance=user,
        )

        if request.method == "POST" and "confirm_delete" in request.POST:
            delete_form = forms.DeleteForm(request.POST)
            if delete_form.is_valid():
                assert request.user == user
                assert delete_form.cleaned_data["confirm_delete"]
                user.is_active = False
                user.save(update_fields=["is_active"])
        elif request.method == "POST" and form.is_valid():
            try:
                form.save()
            except IntegrityError:
                form.add_error("username", "Username taken")
                user.refresh_from_db()

        context["form"] = form
        context["delete_form"] = delete_form

    elif request.user.is_superuser:
        form = forms.UserPermissionsForm(request.POST or None, user=user)

        if request.POST and form.is_valid():
            user.user_permissions.set(form.cleaned_data["permissions"])
            user.blocked_from_reviews = form.cleaned_data["blocked_from_reviews"]
            user.save(update_fields=["blocked_from_reviews"])
            user.manual_tags.set(form.cleaned_data["manual_tags"])

        context["form"] = form

    # Use tabbed template for v1.2
    return render(request, "user_detail_tabs.html", context)


@login_required
def leaderboard(request):
    """Display the user leaderboard based on scores."""
    top_users = get_leaderboard(limit=100)
    return render(
        request,
        "leaderboard.html",
        {
            "top_users": top_users,
        },
    )


def user_liveries(request, pk):
    """AJAX endpoint to load user's livery collection."""
    from django.http import JsonResponse
    from fleet.models import FleetRideLog, FleetPhotoLog
    from vehicles.models import Vehicle
    
    user = get_object_or_404(UserModel, pk=pk)
    
    # Get vehicles user has ridden
    ridden_vehicles = FleetRideLog.objects.filter(
        user=user
    ).values_list('vehicle_id', flat=True).distinct()
    
    # Get vehicles user has photographed
    photographed_vehicles = FleetPhotoLog.objects.filter(
        user=user
    ).values_list('vehicle_id', flat=True).distinct()
    
    # Get all vehicles with liveries
    vehicles = Vehicle.objects.filter(
        id__in=set(list(ridden_vehicles) + list(photographed_vehicles))
    ).select_related('operator', 'livery', 'vehicle_type').exclude(
        livery__isnull=True
    ).order_by('operator__name', 'livery__name')
    
    # Group by operator
    liveries_by_operator = {}
    for vehicle in vehicles:
        if vehicle.operator_id not in liveries_by_operator:
            liveries_by_operator[vehicle.operator_id] = {
                'operator': vehicle.operator,
                'liveries': {}
            }
        
        livery_key = vehicle.livery_id
        if livery_key not in liveries_by_operator[vehicle.operator_id]['liveries']:
            liveries_by_operator[vehicle.operator_id]['liveries'][livery_key] = {
                'livery': vehicle.livery,
                'photographed': vehicle.id in photographed_vehicles,
                'ridden': vehicle.id in ridden_vehicles,
                'count': 1
            }
        else:
            liveries_by_operator[vehicle.operator_id]['liveries'][livery_key]['count'] += 1
            if vehicle.id in photographed_vehicles:
                liveries_by_operator[vehicle.operator_id]['liveries'][livery_key]['photographed'] = True
            if vehicle.id in ridden_vehicles:
                liveries_by_operator[vehicle.operator_id]['liveries'][livery_key]['ridden'] = True
    
    # Generate HTML
    html = ''
    for operator_data in sorted(liveries_by_operator.values(), key=lambda x: x['operator'].name):
        operator = operator_data['operator']
        html += f'<div class="livery-section">'
        html += f'<h3 class="livery-section__title">{operator.name}</h3>'
        html += '<div class="livery-grid">'
        
        for livery_data in operator_data['liveries'].values():
            livery = livery_data['livery']
            photographed = livery_data['photographed']
            ridden = livery_data['ridden']
            count = livery_data['count']
            
            html += '<div class="livery-item">'
            html += f'<div class="livery-item__preview" style="background: {livery.left_css if livery.left_css else livery.colour}"></div>'
            html += '<div class="livery-item__info">'
            html += f'<div class="livery-item__name">{livery.name}</div>'
            html += f'<div class="livery-item__operator">{count} vehicle{"s" if count > 1 else ""}</div>'
            html += '<div class="livery-item__badges">'
            if photographed:
                html += '<span class="livery-item__badge livery-item__badge--photographed">Photographed</span>'
            if ridden:
                html += '<span class="livery-item__badge livery-item__badge--ridden">Ridden</span>'
            html += '</div>'
            html += '</div>'
            html += '</div>'
        
        html += '</div>'
        html += '</div>'
    
    if not html:
        html = '<p>No liveries recorded yet.</p>'
    
    return JsonResponse({'html': html})
