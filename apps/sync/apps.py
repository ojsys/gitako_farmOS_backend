from django.apps import AppConfig


class SyncConfig(AppConfig):
    name = "apps.sync"
    label = "sync"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.activities.models import Activity
        from apps.enterprises.models import Enterprise
        from apps.finance.models import Account, Transaction
        from apps.inventory.models import InventoryItem, InventoryMovement, Store

        from . import registry
        from .models import SyncNote, SyncTag

        registry.register("sync_note", SyncNote, writable_fields=("title", "body"))
        registry.register("sync_tag", SyncTag, writable_fields=("name", "color"))
        registry.register(
            "enterprises_enterprise", Enterprise,
            writable_fields=("farm", "type", "name", "lifecycle_state",
                             "start_date", "end_date", "attrs"),
        )
        registry.register(
            "activities_activity", Activity,
            writable_fields=("enterprise", "type", "occurred_at", "weather",
                             "performed_by", "photo_keys", "cost_kobo",
                             "notes", "attrs"),
        )
        registry.register(
            "inventory_store", Store,
            writable_fields=("farm", "name", "location_note"),
        )
        registry.register(
            "inventory_inventoryitem", InventoryItem,
            writable_fields=("farm", "name", "category", "unit",
                             "valuation_method", "reorder_level", "sku"),
        )
        registry.register(
            "inventory_inventorymovement", InventoryMovement,
            writable_fields=("item", "store", "op", "qty", "unit_cost_kobo",
                             "ref_activity", "transfer_pair_id",
                             "notes", "occurred_at"),
        )
        registry.register(
            "finance_account", Account,
            writable_fields=("farm", "type", "name",
                             "opening_balance_kobo", "currency"),
        )
        registry.register(
            "finance_transaction", Transaction,
            writable_fields=("farm", "account", "kind", "amount_kobo",
                             "party", "enterprise", "activity",
                             "ref_inventory_movement", "receipt_key",
                             "posted_at", "reversal_of", "transfer_pair_id",
                             "description"),
        )
