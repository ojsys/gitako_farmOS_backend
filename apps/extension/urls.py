from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    FarmAdvisoriesView,
    FarmOfficerAccessView,
    OfficerAdvisoryView,
    OfficerAggregateReportView,
    OfficerRequestAccessView,
    OfficerRosterView,
    OfficerVisitViewSet,
)

router = DefaultRouter()
router.register("officer/visits", OfficerVisitViewSet, basename="officer-visits")

urlpatterns = [
    # Officer-facing
    path("officer/roster", OfficerRosterView.as_view(), name="officer-roster"),
    path("officer/request-access", OfficerRequestAccessView.as_view(), name="officer-request-access"),
    path("officer/advisory", OfficerAdvisoryView.as_view(), name="officer-advisory"),
    path("officer/report", OfficerAggregateReportView.as_view(), name="officer-report"),
    # Farmer-facing (tenant-scoped)
    path("access", FarmOfficerAccessView.as_view(), name="farm-officer-access"),
    path("advisories", FarmAdvisoriesView.as_view(), name="farm-advisories"),
] + router.urls
