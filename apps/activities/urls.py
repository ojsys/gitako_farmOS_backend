from django.urls import path
from rest_framework.routers import DefaultRouter

from .media import DevUploadSinkView, MediaUploadView
from .views import ActivityViewSet

router = DefaultRouter()
router.register("activities", ActivityViewSet, basename="activities")

urlpatterns = router.urls + [
    path("media/upload-url", MediaUploadView.as_view(), name="media-upload-url"),
    path("media/dev-upload/<path:key>", DevUploadSinkView.as_view(), name="media-dev-upload"),
]
