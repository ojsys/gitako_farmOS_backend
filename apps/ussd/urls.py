from django.urls import path

from .views import UssdGatewayView

urlpatterns = [
    path("gateway", UssdGatewayView.as_view(), name="ussd-gateway"),
]
