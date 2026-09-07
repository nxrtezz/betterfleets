from rest_framework import routers

from . import views

router = routers.DefaultRouter(
    # trailing_slash=False
)
router.register("vehicles", views.VehicleViewSet)
router.register("liveries", views.LiveryViewSet)
router.register("vehicletypes", views.VehicleTypeViewSet)
router.register("operators", views.OperatorViewSet)
router.register("garages", views.GarageViewSet)
router.register("services", views.ServiceViewSet)
router.register("stops", views.StopViewSet)
router.register("trips", views.TripViewSet)
router.register("vehiclejourneys", views.VehicleJourneyViewSet)
router.register("site-info", views.SiteInfoViewSet, basename="site-info")
router.register("users", views.UserViewSet)