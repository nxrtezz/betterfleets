from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views

urlpatterns = [
    path("discord-link/", views.discord_link, name="discord_link"),
    path("request-driver-status/", views.request_driver_status, name="request_driver_status"),
    path("users/<int:pk>/driver-stats/", views.driver_stats, name="driver_stats"),
    path("users/<int:pk>/liveries/", views.user_liveries, name="user_liveries"),
    path("users/", views.user_list, name="user_list"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    # Account management pages
    path("dashboard/", login_required(views.account_dashboard), name="account_dashboard"),
    path("profile/", login_required(views.account_profile), name="account_profile"),
    path("email/", login_required(views.account_email), name="account_email"),
    path("password/", login_required(views.account_password), name="account_password"),
    path("sessions/", login_required(views.account_sessions), name="account_sessions"),
]
