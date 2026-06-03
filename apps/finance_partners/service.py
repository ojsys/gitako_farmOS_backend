"""Embedded-finance transitions (PRD M18).

Loan lifecycle: draft → submitted (snapshot M16 score, route to partner) →
offered → accepted → disbursed (money out via payments seam) → repaid.
Partner-side steps (offer/decline) are exposed for the partner portal; in v1 a
manager can also simulate them for the closed beta.
"""
from __future__ import annotations

from django.db import transaction as db_transaction

from apps.creditscore.engine import compute_score
from apps.payments.providers import get_payment_provider, new_reference

from .models import LoanApplication


class FinanceError(Exception):
    """Invalid finance transition (maps to 400)."""


@db_transaction.atomic
def submit_loan(loan: LoanApplication, partner=None) -> LoanApplication:
    if loan.status not in (LoanApplication.STATUS_DRAFT,):
        raise FinanceError("Only a draft application can be submitted.")
    # Snapshot the farm's credit score at submission (M16).
    loan.credit_score_snapshot = compute_score(loan.farm)["score"]
    if partner is not None:
        loan.partner = partner
    loan.status = LoanApplication.STATUS_SUBMITTED
    loan.save(update_fields=["credit_score_snapshot", "partner", "status", "updated_at"])
    return loan


def offer_loan(loan: LoanApplication, *, terms: dict) -> LoanApplication:
    if loan.status != LoanApplication.STATUS_SUBMITTED:
        raise FinanceError("Only a submitted application can be offered.")
    loan.offer_terms = terms or {}
    loan.status = LoanApplication.STATUS_OFFERED
    loan.save(update_fields=["offer_terms", "status", "updated_at"])
    return loan


def accept_loan(loan: LoanApplication) -> LoanApplication:
    if loan.status != LoanApplication.STATUS_OFFERED:
        raise FinanceError("Only an offered loan can be accepted.")
    loan.status = LoanApplication.STATUS_ACCEPTED
    loan.save(update_fields=["status", "updated_at"])
    return loan


def disburse_loan(loan: LoanApplication) -> LoanApplication:
    if loan.status != LoanApplication.STATUS_ACCEPTED:
        raise FinanceError("Only an accepted loan can be disbursed.")
    recipient = loan.farm.owner.phone or str(loan.farm.id)
    ref = new_reference("loan_disb")
    result = get_payment_provider().transfer(
        amount_kobo=loan.amount_kobo, recipient=recipient, reference=ref,
        description=f"Loan disbursement {loan.id}",
    )
    if not result.ok:
        raise FinanceError("Disbursement transfer failed.")
    loan.status = LoanApplication.STATUS_DISBURSED
    loan.disbursement_reference = result.reference
    loan.save(update_fields=["status", "disbursement_reference", "updated_at"])
    return loan


def repay_loan(loan: LoanApplication) -> LoanApplication:
    if loan.status != LoanApplication.STATUS_DISBURSED:
        raise FinanceError("Only a disbursed loan can be repaid.")
    loan.status = LoanApplication.STATUS_REPAID
    loan.save(update_fields=["status", "updated_at"])
    return loan
