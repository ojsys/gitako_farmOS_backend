from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import EnterpriseViewSet, PlannedTasksView, SeasonTaskViewSet

router = DefaultRouter()
router.register("enterprises", EnterpriseViewSet, basename="enterprises")
router.register("season-tasks", SeasonTaskViewSet, basename="season-tasks")

urlpatterns = router.urls + [
    path("planned-tasks", PlannedTasksView.as_view(), name="planned-tasks"),
]
