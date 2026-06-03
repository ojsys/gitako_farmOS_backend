from __future__ import annotations

from django.db.models import Sum
from rest_framework import serializers

from .models import Account, Transaction


class AccountSerializer(serializers.ModelSerializer):
    balance_kobo = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = (
            "id", "farm", "tenant_id", "type", "name",
            "opening_balance_kobo", "currency", "balance_kobo",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "farm", "tenant_id", "balance_kobo",
            "created_at", "updated_at",
        )

    def get_balance_kobo(self, obj):
        return _balance_kobo(obj)


class TransactionSerializer(serializers.ModelSerializer):
    account_name = serializers.SerializerMethodField()
    party_name = serializers.SerializerMethodField()
    enterprise_name = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = (
            "id", "farm", "tenant_id", "account", "account_name",
            "kind", "amount_kobo",
            "party", "party_name", "enterprise", "enterprise_name",
            "activity", "ref_inventory_movement", "receipt_key",
            "posted_at", "reversal_of", "transfer_pair_id", "description",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "farm", "tenant_id",
            "account_name", "party_name", "enterprise_name",
            "created_at", "updated_at",
        )

    def get_account_name(self, obj):
        return obj.account.name if obj.account_id else None

    def get_party_name(self, obj):
        return obj.party.name if obj.party_id else None

    def get_enterprise_name(self, obj):
        return obj.enterprise.name if obj.enterprise_id else None


# ---------- helpers ----------

def _balance_kobo(account: Account) -> int:
    """Opening balance + sum of all transaction amounts (already signed)."""
    posted = (
        account.transactions.filter(deleted_at__isnull=True)
        .aggregate(s=Sum("amount_kobo"))["s"]
        or 0
    )
    return account.opening_balance_kobo + posted
