from rest_framework.routers import DefaultRouter

from .views import (
    InventoryItemViewSet,
    InventoryMovementViewSet,
    InventorySummaryView,
    StoreViewSet,
)

router = DefaultRouter()
router.register("stores", StoreViewSet, basename="stores")
router.register("inventory-items", InventoryItemViewSet, basename="inventory-items")
router.register("inventory-movements", InventoryMovementViewSet, basename="inventory-movements")
router.register("inventory-summary", InventorySummaryView, basename="inventory-summary")

urlpatterns = router.urls
