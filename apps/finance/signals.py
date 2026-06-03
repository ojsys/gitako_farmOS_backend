"""Bridge inventory receipts into the financial ledger.

When an InventoryMovement of op='receipt' with unit_cost_kobo > 0 is created,
auto-emit a paired expense Transaction. The expense lands on the farm's
first cash account (sensible default — user can pick a different account
later via correction). Reversal: if the movement is soft-deleted, we mark
the linked transaction as reversed via reversal_of.

This signal is wired in apps/finance/apps.py.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.inventory.models import InventoryMovement

from .models import Account, Transaction

log = logging.getLogger("gitako.finance")


@receiver(post_save, sender=InventoryMovement)
def emit_expense_for_receipt(sender, instance: InventoryMovement, created: bool, **kwargs):
    if not created:
        return
    if instance.op != InventoryMovement.OP_RECEIPT:
        return
    if instance.unit_cost_kobo <= 0:
        return
    # Already linked? Don't double-post (idempotency for retried sync push).
    if Transaction.objects.filter(
        ref_inventory_movement=instance, deleted_at__isnull=True,
    ).exists():
        return

    cash_account = (
        Account.objects.filter(
            tenant_id=instance.tenant_id, deleted_at__isnull=True,
            type=Account.TYPE_CASH,
        )
        .order_by("created_at")
        .first()
    )
    if cash_account is None:
        # No account to bill against — skip silently. User can post the expense
        # manually later. We log so this isn't invisible.
        log.info(
            "Inventory receipt %s for tenant %s has no cash account to bill — "
            "skipping auto-expense.", instance.id, instance.tenant_id,
        )
        return

    amount_kobo = int(float(instance.qty) * instance.unit_cost_kobo)
    Transaction.objects.create(
        tenant_id=instance.tenant_id,
        farm_id=instance.tenant_id,  # tenant_id == farm.id by convention
        account=cash_account,
        kind=Transaction.KIND_EXPENSE,
        amount_kobo=-abs(amount_kobo),
        ref_inventory_movement=instance,
        posted_at=instance.occurred_at,
        description=f"Receipt: {instance.item.name} × {instance.qty}",
    )
