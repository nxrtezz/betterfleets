from django.urls import path
from . import views

app_name = "favourites"

urlpatterns = [
    path("add/", views.add_favourite, name="add"),
    path("remove/<int:favourite_id>/", views.remove_favourite, name="remove"),
    path("toggle/", views.toggle_favourite, name="toggle"),
]
