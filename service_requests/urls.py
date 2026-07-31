from django.urls import path
from . import views

app_name = "service_requests"

urlpatterns = [
    path("", views.RequestListView.as_view(), name="list"),
    path("<int:id>/", views.RequestDetailView.as_view(), name="detail"),
    path("create/", views.RequestCreateView.as_view(), name="create"),
    path("<int:id>/edit/", views.RequestUpdateView.as_view(), name="update"),
    path("<int:id>/comment/", views.add_comment, name="add_comment"),
    path("<int:id>/status/", views.change_status, name="change_status"),
]
