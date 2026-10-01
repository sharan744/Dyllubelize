from django.contrib import admin
from .models import SiteSetting


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ("company_name", "phone", "email", "currency_code",
                    "tax_label", "tax_percent")
    fieldsets = (
        ("Company", {"fields": ("company_name", "tagline", "address",
                                 "phone", "email", "tax_id")}),
        ("Currency", {"fields": ("currency_symbol", "currency_code")}),
        ("Accounting", {
            "fields": ("accounts_follow_invoice_visibility",),
            "description": (
                "When enabled, Accounts reports temporarily follow each invoice's "
                "Show in UI selection. When disabled, the full accounting ledger is used."
            ),
        }),
        ("Tax / VAT", {"fields": ("tax_enabled", "tax_label", "tax_percent")}),
        ("Quotation", {"fields": ("quote_validity_days", "quote_terms")}),
    )

    def has_add_permission(self, request):
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
