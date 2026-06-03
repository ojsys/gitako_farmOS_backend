"""Escrow state-machine transitions (PRD M17).

Each transition validates the current state, calls the payment seam where money
moves, and advances the Contract. Kept separate from views so the rules are
testable in isolation and reused by any caller.
"""
from __future__ import annotations

from django.db import transaction as db_transaction

from apps.payments.providers import get_payment_provider, new_reference

from .models import Contract, Offer


class EscrowError(Exception):
    """Invalid escrow transition (maps to 400 in views)."""


@db_transaction.atomic
def accept_offer(offer: Offer) -> Contract:
    if offer.status != Offer.STATUS_PENDING:
        raise EscrowError("Only a pending offer can be accepted.")
    if hasattr(offer, "contract"):
        raise EscrowError("This offer already has a contract.")
    offer.status = Offer.STATUS_ACCEPTED
    offer.save(update_fields=["status", "updated_at"])
    return Contract.objects.create(
        offer=offer,
        listing=offer.listing,
        seller_farm=offer.listing.farm,
        buyer=offer.buyer,
        amount_kobo=offer.offer_price_kobo,
        state=Contract.STATE_AGREED,
    )


def fund_escrow(contract: Contract) -> Contract:
    """Buyer funds escrow — money in via the payment provider."""
    if contract.state != Contract.STATE_AGREED:
        raise EscrowError(f"Cannot fund a contract in state '{contract.state}'.")
    ref = new_reference("escrow_chg")
    result = get_payment_provider().charge(
        amount_kobo=contract.amount_kobo, reference=ref,
        description=f"Escrow funding for contract {contract.id}",
    )
    if not result.ok:
        raise EscrowError("Payment failed — escrow not funded.")
    contract.state = Contract.STATE_FUNDED
    contract.charge_reference = result.reference
    contract.save(update_fields=["state", "charge_reference", "updated_at"])
    return contract


def mark_delivered(contract: Contract) -> Contract:
    if contract.state != Contract.STATE_FUNDED:
        raise EscrowError("Only a funded contract can be marked delivered.")
    contract.state = Contract.STATE_DELIVERED
    contract.save(update_fields=["state", "updated_at"])
    return contract


def record_qa(contract: Contract, *, passed: bool, notes: str = "") -> Contract:
    """QA-at-pickup: buyer inspects on delivery. Pass → ready to release;
    fail → disputed."""
    if contract.state != Contract.STATE_DELIVERED:
        raise EscrowError("QA can only be recorded on a delivered contract.")
    contract.qa_result = Contract.QA_PASSED if passed else Contract.QA_FAILED
    contract.qa_notes = notes
    contract.state = Contract.STATE_DELIVERED if passed else Contract.STATE_DISPUTED
    contract.save(update_fields=["qa_result", "qa_notes", "state", "updated_at"])
    return contract


def release_funds(contract: Contract) -> Contract:
    """Release escrow to the seller. Allowed after delivery with QA not failed
    (passed, or pending where the buyer accepts as-is), or to resolve a dispute
    in the seller's favour."""
    if contract.state not in (Contract.STATE_DELIVERED, Contract.STATE_DISPUTED):
        raise EscrowError(f"Cannot release from state '{contract.state}'.")
    if contract.state == Contract.STATE_DELIVERED and contract.qa_result == Contract.QA_FAILED:
        raise EscrowError("QA failed — resolve the dispute before releasing.")
    recipient = contract.seller_farm.owner.phone or str(contract.seller_farm.id)
    ref = new_reference("escrow_rel")
    result = get_payment_provider().transfer(
        amount_kobo=contract.amount_kobo, recipient=recipient, reference=ref,
        description=f"Escrow release for contract {contract.id}",
    )
    if not result.ok:
        raise EscrowError("Transfer failed — funds not released.")
    contract.state = Contract.STATE_RELEASED
    contract.release_reference = result.reference
    contract.save(update_fields=["state", "release_reference", "updated_at"])
    # Mark the listing sold.
    contract.listing.status = "sold"
    contract.listing.save(update_fields=["status", "updated_at"])
    return contract


def refund_buyer(contract: Contract) -> Contract:
    """Resolve a dispute in the buyer's favour — return escrow."""
    if contract.state not in (Contract.STATE_FUNDED, Contract.STATE_DELIVERED, Contract.STATE_DISPUTED):
        raise EscrowError(f"Cannot refund from state '{contract.state}'.")
    ref = new_reference("escrow_ref")
    recipient = contract.buyer.phone or str(contract.buyer.id)
    result = get_payment_provider().transfer(
        amount_kobo=contract.amount_kobo, recipient=recipient, reference=ref,
        description=f"Escrow refund for contract {contract.id}",
    )
    if not result.ok:
        raise EscrowError("Refund transfer failed.")
    contract.state = Contract.STATE_REFUNDED
    contract.save(update_fields=["state", "updated_at"])
    return contract
