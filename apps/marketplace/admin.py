from django.contrib import admin

from .models import Contract, Listing, Offer


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "farm", "status", "price_kobo", "created_at")
    list_filter = ("kind", "status", "region")
    search_fields = ("title", "description", "farm__name")
    raw_id_fields = ("farm",)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("listing", "buyer", "offer_price_kobo", "status", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("listing", "buyer")


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("id", "listing", "seller_farm", "buyer", "amount_kobo", "state", "qa_result")
    list_filter = ("state", "qa_result")
    raw_id_fields = ("offer", "listing", "seller_farm", "buyer")
