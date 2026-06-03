"""Embedded Finance Rails (PRD M18).

"Loan applications routed to partner banks/MFIs. Insurance quotes from partners
(weather-index, livestock mortality). Input financing (buy now, pay after
harvest) with partner suppliers."

The farm applies; the application carries a snapshot of the farm's M16 credit
score; a partner (M14 Partner) is the routing target. Disbursement and repayment
move money through the shared payments seam. Insurance quotes and input-financing
requests follow the same apply→partner-decision pattern.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.farms.models import Farm
from apps.partners.models import Partner


class LoanApplication(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"        # routed to partner
    STATUS_OFFERED = "offered"            # partner made an offer
    STATUS_ACCEPTED = "accepted"          # farmer accepted the offer
    STATUS_DISBURSED = "disbursed"        # funds sent
    STATUS_REPAID = "repaid"
    STATUS_DEFAULTED = "defaulted"
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_OFFERED, "Offered"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_DISBURSED, "Disbursed"),
        (STATUS_REPAID, "Repaid"),
        (STATUS_DEFAULTED, "Defaulted"),
        (STATUS_DECLINED, "Declined"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="loan_applications")
    partner = models.ForeignKey(
        Partner, null=True, blank=True, on_delete=models.SET_NULL, related_name="loan_applications",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="loan_applications",
    )
    amount_kobo = models.BigIntegerField()
    purpose = models.CharField(max_length=200, blank=True)
    term_days = models.PositiveIntegerField(default=180)
    # Snapshot of the farm's credit score at application time (M16).
    credit_score_snapshot = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    # Partner's offer terms (interest, etc.) — free-form for v1.
    offer_terms = models.JSONField(default=dict, blank=True)
    disbursement_reference = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Loan {self.amount_kobo} for {self.farm_id} ({self.status})"


class InsuranceQuote(models.Model):
    KIND_WEATHER = "weather_index"
    KIND_MORTALITY = "livestock_mortality"
    KIND_CHOICES = [(KIND_WEATHER, "Weather-index"), (KIND_MORTALITY, "Livestock mortality")]

    STATUS_REQUESTED = "requested"
    STATUS_QUOTED = "quoted"
    STATUS_BOUND = "bound"      # farmer accepted/paid
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_QUOTED, "Quoted"),
        (STATUS_BOUND, "Bound"),
        (STATUS_DECLINED, "Declined"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="insurance_quotes")
    partner = models.ForeignKey(
        Partner, null=True, blank=True, on_delete=models.SET_NULL, related_name="insurance_quotes",
    )
    kind = models.CharField(max_length=24, choices=KIND_CHOICES)
    coverage_kobo = models.BigIntegerField(help_text="Sum insured in kobo.")
    premium_kobo = models.BigIntegerField(default=0, help_text="Quoted premium in kobo.")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} quote for {self.farm_id} ({self.status})"


class InputFinancing(models.Model):
    """Buy-now-pay-after-harvest for farm inputs, fronted by a partner supplier."""

    STATUS_REQUESTED = "requested"
    STATUS_APPROVED = "approved"
    STATUS_FULFILLED = "fulfilled"   # inputs delivered
    STATUS_REPAID = "repaid"
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_FULFILLED, "Fulfilled"),
        (STATUS_REPAID, "Repaid"),
        (STATUS_DECLINED, "Declined"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="input_financing")
    partner = models.ForeignKey(
        Partner, null=True, blank=True, on_delete=models.SET_NULL, related_name="input_financing",
    )
    description = models.CharField(max_length=255, help_text="Inputs requested (e.g. 10 bags NPK).")
    value_kobo = models.BigIntegerField()
    repay_after_days = models.PositiveIntegerField(default=120)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Input financing {self.value_kobo} for {self.farm_id} ({self.status})"
