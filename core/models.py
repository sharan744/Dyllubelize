from decimal import Decimal

from django.db import models


class SiteSetting(models.Model):
    """Singleton holding company details shown on printed documents."""

    company_name = models.CharField(max_length=200, default="United Distributors Ltd")
    tagline = models.CharField(max_length=200, blank=True, default="Distribution & Supply")
    address = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=60, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    tax_id = models.CharField("Company Tax ID (TIN)", max_length=60, blank=True, default="")
    currency_symbol = models.CharField(max_length=5, default="$")
    currency_code = models.CharField(max_length=5, default="BZD")

    # Accounts / financial reporting visibility
    accounts_follow_invoice_visibility = models.BooleanField(
        "Accounts follow invoice Show in UI",
        default=False,
        help_text=(
            "When enabled, Accounts and invoice-based financial reports use only "
            "invoices whose Show in UI checkbox is enabled. When disabled, "
            "accounting uses the complete ledger as normal."
        ),
    )

    # Tax / VAT — fully configurable from the admin
    tax_enabled = models.BooleanField(
        "Show tax on quotations", default=True,
        help_text="Untick to hide the tax line entirely.",
    )
    tax_label = models.CharField(
        "Tax label", max_length=20, default="GST",
        help_text="Name shown for the tax, e.g. GST, VAT, IVA.",
    )
    tax_percent = models.DecimalField(
        "Tax rate (%)", max_digits=5, decimal_places=2, default=Decimal("12.5"),
        help_text="e.g. 12.5 for Belize GST, 0 for exempt.",
    )

    # Salesperson incentive
    incentive_percent = models.DecimalField(
        "Sales incentive (% of margin)", max_digits=5, decimal_places=2, default=10,
        help_text="Default incentive paid to a salesperson as a % of the gross margin they generate.",
    )

    # Quotation defaults
    quote_validity_days = models.PositiveIntegerField(
        "Quotation validity (days)", default=15,
        help_text="How many days a quotation stays valid.",
    )
    quote_terms = models.TextField(
        "Quotation terms & notes", blank=True,
        default="Prices are quoted in MXN and are valid for the period shown above. "
                "Delivery times are estimated and confirmed on order acceptance.",
    )

    class Meta:
        verbose_name = "Site Setting"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return self.company_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
