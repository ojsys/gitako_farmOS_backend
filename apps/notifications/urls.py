from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    DigestPreferenceView,
    NotificationRuleViewSet,
    NotificationViewSet,
)

# SimpleRouter (no api-root view) so the empty-prefix notifications viewset's
# list route owns "^$" cleanly. The rules router (prefixed) must resolve before
# the catch-all notifications viewset.
rules_router = SimpleRouter()
rules_router.register("rules", NotificationRuleViewSet, basename="notification-rules")

notifications_router = SimpleRouter()
notifications_router.register("", NotificationViewSet, basename="notifications")

urlpatterns = [
    path("digest-preference", DigestPreferenceView.as_view(), name="digest-preference"),
    *rules_router.urls,
    *notifications_router.urls,
]
