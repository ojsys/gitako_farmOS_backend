from django.urls import path

from .views import AnomaliesView, ChatView, DiagnoseView

urlpatterns = [
    path("chat", ChatView.as_view(), name="copilot-chat"),
    path("diagnose", DiagnoseView.as_view(), name="copilot-diagnose"),
    path("anomalies", AnomaliesView.as_view(), name="copilot-anomalies"),
]
