from django.urls import path

from .consent_views import FarmConsentView
from .views import (
    ActivityEventsView,
    CreditScoreView,
    FarmAggregateView,
    FarmRegistryView,
    PartnerConsentsView,
)

urlpatterns = [
    # Partner-facing public API (API-key auth). No trailing slash.
    path("v1/consents", PartnerConsentsView.as_view(), name="partner-consents"),
    path("v1/farms/<uuid:farm_id>/registry", FarmRegistryView.as_view(), name="partner-registry"),
    path("v1/farms/<uuid:farm_id>/aggregate", FarmAggregateView.as_view(), name="partner-aggregate"),
    path("v1/farms/<uuid:farm_id>/activity-events", ActivityEventsView.as_view(), name="partner-activity"),
    path("v1/farms/<uuid:farm_id>/credit-score", CreditScoreView.as_view(), name="partner-credit-score"),
    # Farmer-facing consent control (Gitako-user auth + X-Tenant-Id).
    path("consent", FarmConsentView.as_view(), name="farm-consent"),
]
