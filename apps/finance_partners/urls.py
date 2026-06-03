from rest_framework.routers import DefaultRouter

from .views import InputFinancingViewSet, InsuranceQuoteViewSet, LoanApplicationViewSet

router = DefaultRouter()
router.register("loans", LoanApplicationViewSet, basename="loans")
router.register("insurance", InsuranceQuoteViewSet, basename="insurance")
router.register("input-financing", InputFinancingViewSet, basename="input-financing")

urlpatterns = router.urls
