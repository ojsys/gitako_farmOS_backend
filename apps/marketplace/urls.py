from rest_framework.routers import DefaultRouter

from .escrow_views import ContractViewSet, OfferViewSet
from .views import ListingBrowseView, MyListingViewSet

router = DefaultRouter()
router.register("listings", ListingBrowseView, basename="listings")
router.register("my-listings", MyListingViewSet, basename="my-listings")
router.register("offers", OfferViewSet, basename="offers")
router.register("contracts", ContractViewSet, basename="contracts")

urlpatterns = router.urls
