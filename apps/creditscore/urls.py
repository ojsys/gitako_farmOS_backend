from django.urls import path

from .views import MyScoreView

urlpatterns = [
    path("score", MyScoreView.as_view(), name="credit-score"),
]
