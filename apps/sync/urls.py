from django.urls import path

from .views import PullView, PushView

urlpatterns = [
    path("push", PushView.as_view(), name="sync-push"),
    path("pull", PullView.as_view(), name="sync-pull"),
]
