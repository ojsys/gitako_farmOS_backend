from django.contrib import admin
from django.utils.html import format_html

from .models import Account, Transaction
from .serializers import _balance_kobo


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "balance_display", "currency", "farm")
    list_filter = ("type", "currency")
    search_fields = ("name", "farm__name")
    raw_id_fields = ("farm",)
    readonly_fields = (
        "id", "tenant_id", "balance_display",
        "created_at", "updated_at", "deleted_at",
    )

    @admin.display(description="Balance")
    def balance_display(self, obj):
        return f"₦{_balance_kobo(obj) / 100:,.0f}"


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "posted_at", "kind_chip", "amount_display", "account",
        "enterprise", "party", "description",
    )
    list_filter = ("kind", "account", "posted_at")
    search_fields = ("description", "account__name", "party__name", "enterprise__name")
    raw_id_fields = (
        "farm", "account", "party", "enterprise", "activity",
        "ref_inventory_movement", "reversal_of",
    )
    readonly_fields = (
        "id", "tenant_id", "transfer_pair_id",
        "created_at", "updated_at", "deleted_at",
    )
    date_hierarchy = "posted_at"

    @admin.display(description="Kind", ordering="kind")
    def kind_chip(self, obj):
        palette = {
            "income": ("#1F8B4C", "+"),
            "expense": ("#B23A2B", "−"),
            "transfer": ("#1F6F8B", "↔"),
        }
        color, icon = palette.get(obj.kind, ("#5A6760", ""))
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:6px;'
            'font-weight:600;font-size:11px;text-transform:uppercase;">{} {}</span>',
            color, color, icon, obj.kind,
        )

    @admin.display(description="Amount", ordering="amount_kobo")
    def amount_display(self, obj):
        sign = "+" if obj.amount_kobo > 0 else "−"
        color = "#1F8B4C" if obj.amount_kobo > 0 else "#B23A2B"
        return format_html(
            '<span style="color:{};font-weight:600;">{}₦{}</span>',
            color, sign, f"{abs(obj.amount_kobo) / 100:,.0f}",
        )
