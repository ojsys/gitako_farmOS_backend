from rest_framework.routers import DefaultRouter

from .views import FarmViewSet, MyMembershipsViewSet, PartyViewSet

router = DefaultRouter()
router.register("farms", FarmViewSet, basename="farms")
router.register("parties", PartyViewSet, basename="parties")
router.register("memberships", MyMembershipsViewSet, basename="memberships")

urlpatterns = router.urls
