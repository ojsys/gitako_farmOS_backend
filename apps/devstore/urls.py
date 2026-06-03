from rest_framework.routers import DefaultRouter

from .views import FarmInstallViewSet, ModuleBrowseView

router = DefaultRouter()
router.register("modules", ModuleBrowseView, basename="modules")
router.register("installs", FarmInstallViewSet, basename="installs")

urlpatterns = router.urls
