from django.urls import path
from . import views

urlpatterns = [
    path("block-view", views.block_view, name="block_view"),
]
