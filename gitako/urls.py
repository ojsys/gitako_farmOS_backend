from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

admin.site.site_header = "Gitako · Operations"
admin.site.site_title = "Gitako Ops"
admin.site.index_title = "Operations dashboard"
admin.site.site_url = None  # hide the default "View site →" link


def root(_request):
    """Tiny index at / so the base URL is reachable (the API is under /api/).

    Plain Django view (not DRF) so it needs no auth and never touches the DB —
    a safe health check that works even before migrations run.
    """
    return JsonResponse(
        {
            "service": "Gitako Farm OS API",
            "status": "ok",
            "docs": "/api/schema/swagger-ui/",
            "schema": "/api/schema/",
            "admin": "/admin/",
        }
    )


urlpatterns = [
    path("", root, name="root"),
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.farms.urls")),
    path("api/", include("apps.enterprises.urls")),
    path("api/", include("apps.activities.urls")),
    path("api/", include("apps.inventory.urls")),
    path("api/", include("apps.finance.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("api/copilot/", include("apps.copilot.urls")),
    path("api/marketplace/", include("apps.marketplace.urls")),
    path("api/partners/", include("apps.partners.urls")),
    path("api/extension/", include("apps.extension.urls")),
    path("api/creditscore/", include("apps.creditscore.urls")),
    path("api/finance/", include("apps.finance_partners.urls")),
    path("api/ussd/", include("apps.ussd.urls")),
    path("api/devstore/", include("apps.devstore.urls")),
    path("api/sync/", include("apps.sync.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
