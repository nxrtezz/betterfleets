from django.urls import path
from . import views

app_name = "service_logging"

urlpatterns = [
    path("log/", views.log_service, name="log"),
    path("toggle-ridden/<int:service_id>/", views.toggle_service_ridden, name="toggle_ridden"),
    path("toggle-photographed/<int:service_id>/", views.toggle_service_photographed, name="toggle_photographed"),
]
