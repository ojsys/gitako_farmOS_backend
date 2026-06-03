from __future__ import annotations

from rest_framework import serializers

from .models import InputFinancing, InsuranceQuote, LoanApplication


class LoanApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanApplication
        fields = (
            "id", "farm", "partner", "applicant", "amount_kobo", "purpose", "term_days",
            "credit_score_snapshot", "status", "offer_terms", "disbursement_reference",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "farm", "applicant", "credit_score_snapshot", "status",
            "disbursement_reference", "created_at", "updated_at",
        )


class InsuranceQuoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsuranceQuote
        fields = (
            "id", "farm", "partner", "kind", "coverage_kobo", "premium_kobo",
            "status", "details", "created_at", "updated_at",
        )
        read_only_fields = ("id", "farm", "premium_kobo", "status", "created_at", "updated_at")


class InputFinancingSerializer(serializers.ModelSerializer):
    class Meta:
        model = InputFinancing
        fields = (
            "id", "farm", "partner", "description", "value_kobo", "repay_after_days",
            "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "farm", "status", "created_at", "updated_at")
