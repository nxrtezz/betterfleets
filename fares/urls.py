from django.urls import path
from . import views


urlpatterns = [
    path("", views.index),
    path("preview", views.netex_preview, name="netex_preview"),
    path("datasets/<int:pk>", views.DataSetDetailView.as_view(), name="dataset_detail"),
    path("tickets/<int:pk>", views.TicketDetailView.as_view(), name="ticket_detail"),
    path("tariffs/<int:pk>", views.TariffDetailView.as_view(), name="tariff_detail"),
    path("tables/<int:pk>", views.FareTableDetailView.as_view(), name="table_detail"),
]
