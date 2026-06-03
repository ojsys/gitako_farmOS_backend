from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from .models import Enterprise, EnterprisePlan, SeasonTask


class EnterpriseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Enterprise
        fields = (
            "id", "farm", "tenant_id", "type", "name", "lifecycle_state",
            "start_date", "end_date", "attrs", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")

    HERD_SPECIES = {"cattle", "goat", "sheep", "pig"}
    POND_SPECIES = {"catfish", "tilapia", "other"}

    def validate(self, data):
        type_ = data.get("type") or getattr(self.instance, "type", None)
        attrs = data.get("attrs", {})
        if type_ == Enterprise.TYPE_CROP:
            required = {"crop", "area_ha"}
            missing = required - set(attrs)
            if missing:
                raise serializers.ValidationError(
                    {"attrs": f"crop_cycle requires {sorted(missing)}"}
                )
        elif type_ == Enterprise.TYPE_FLOCK:
            required = {"kind", "bird_count"}
            missing = required - set(attrs)
            if missing:
                raise serializers.ValidationError(
                    {"attrs": f"flock requires {sorted(missing)}"}
                )
        elif type_ == Enterprise.TYPE_HERD:
            required = {"species", "herd_size"}
            missing = required - set(attrs)
            if missing:
                raise serializers.ValidationError(
                    {"attrs": f"herd requires {sorted(missing)}"}
                )
            species = attrs.get("species")
            if species not in self.HERD_SPECIES:
                raise serializers.ValidationError(
                    {"attrs": f"herd species must be one of {sorted(self.HERD_SPECIES)}"}
                )
        elif type_ == Enterprise.TYPE_POND:
            required = {"species", "fingerling_count"}
            missing = required - set(attrs)
            if missing:
                raise serializers.ValidationError(
                    {"attrs": f"pond requires {sorted(missing)}"}
                )
            species = attrs.get("species")
            if species not in self.POND_SPECIES:
                raise serializers.ValidationError(
                    {"attrs": f"pond species must be one of {sorted(self.POND_SPECIES)}"}
                )
        elif type_ == Enterprise.TYPE_PROCESSING:
            if "process" not in attrs:
                raise serializers.ValidationError(
                    {"attrs": "processing_line requires 'process' (e.g. cassava_garri)"}
                )
        return data


class EnterprisePlanSerializer(serializers.ModelSerializer):
    """Plan editing surface + computed money summary.

    Writable: budget_lines, expected_yield_kg, expected_unit_price_kobo,
    price_reference, notes, locked_at.
    Computed (read-only): total_budget_kobo, expected_revenue_kobo,
    expected_profit_kobo, break_even_unit_price_kobo, roi_pct.
    """

    total_budget_kobo = serializers.SerializerMethodField()
    expected_revenue_kobo = serializers.SerializerMethodField()
    expected_profit_kobo = serializers.SerializerMethodField()
    break_even_unit_price_kobo = serializers.SerializerMethodField()
    roi_pct = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()

    class Meta:
        model = EnterprisePlan
        fields = (
            "enterprise", "tenant_id",
            "budget_lines",
            "expected_yield_kg",
            "expected_unit_price_kobo",
            "price_reference",
            "notes",
            "locked_at",
            "is_locked",
            "total_budget_kobo",
            "expected_revenue_kobo",
            "expected_profit_kobo",
            "break_even_unit_price_kobo",
            "roi_pct",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "enterprise", "tenant_id",
            "is_locked",
            "total_budget_kobo", "expected_revenue_kobo",
            "expected_profit_kobo", "break_even_unit_price_kobo", "roi_pct",
            "created_at", "updated_at",
        )

    def validate_budget_lines(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("budget_lines must be a list.")
        for i, line in enumerate(value):
            if not isinstance(line, dict):
                raise serializers.ValidationError(f"line {i} must be an object")
            for key in ("id", "label", "planned_kobo"):
                if key not in line:
                    raise serializers.ValidationError(f"line {i} missing '{key}'")
            try:
                int(line["planned_kobo"])
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError(
                    f"line {i} planned_kobo must be an integer (kobo)"
                ) from exc
        return value

    # --- computed ---

    def _total_budget(self, obj) -> int:
        return sum(int(line.get("planned_kobo") or 0) for line in (obj.budget_lines or []))

    def get_total_budget_kobo(self, obj) -> int:
        return self._total_budget(obj)

    def get_expected_revenue_kobo(self, obj) -> int:
        if obj.expected_yield_kg is None or obj.expected_unit_price_kobo is None:
            return 0
        return int(Decimal(obj.expected_yield_kg) * Decimal(obj.expected_unit_price_kobo))

    def get_expected_profit_kobo(self, obj) -> int:
        return self.get_expected_revenue_kobo(obj) - self._total_budget(obj)

    def get_break_even_unit_price_kobo(self, obj) -> int | None:
        if not obj.expected_yield_kg or obj.expected_yield_kg == 0:
            return None
        return int(Decimal(self._total_budget(obj)) / Decimal(obj.expected_yield_kg))

    def get_roi_pct(self, obj) -> float | None:
        total = self._total_budget(obj)
        if total == 0:
            return None
        return round(self.get_expected_profit_kobo(obj) / total * 100, 1)

    def get_is_locked(self, obj) -> bool:
        return obj.locked_at is not None


class SeasonTaskSerializer(serializers.ModelSerializer):
    assigned_to_label = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = SeasonTask
        fields = (
            "id", "enterprise", "activity_type", "label", "notes",
            "target_date", "source", "status", "assigned_to", "assigned_to_label",
            "is_overdue", "completed_at", "completed_activity",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_assigned_to_label(self, obj):
        u = obj.assigned_to
        if not u:
            return None
        return u.full_name or u.phone or ""

    def get_is_overdue(self, obj):
        from django.utils import timezone
        return obj.status == SeasonTask.STATUS_PENDING and obj.target_date < timezone.localdate()
