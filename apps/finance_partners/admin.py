from django.contrib import admin

from .models import InputFinancing, InsuranceQuote, LoanApplication


@admin.register(LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display = ("farm", "partner", "amount_kobo", "status", "credit_score_snapshot", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("farm", "partner", "applicant")


@admin.register(InsuranceQuote)
class InsuranceQuoteAdmin(admin.ModelAdmin):
    list_display = ("farm", "partner", "kind", "coverage_kobo", "premium_kobo", "status")
    list_filter = ("kind", "status")
    raw_id_fields = ("farm", "partner")


@admin.register(InputFinancing)
class InputFinancingAdmin(admin.ModelAdmin):
    list_display = ("farm", "partner", "description", "value_kobo", "status")
    list_filter = ("status",)
    raw_id_fields = ("farm", "partner")
