from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountViewSet,
    CashPositionView,
    PnlView,
    TransactionViewSet,
)

router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="accounts")
router.register("transactions", TransactionViewSet, basename="transactions")

urlpatterns = router.urls + [
    path("finance/cash-position", CashPositionView.as_view(), name="cash-position"),
    path("finance/pnl", PnlView.as_view(), name="pnl"),
]
