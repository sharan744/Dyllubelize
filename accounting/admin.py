from django.contrib import admin

from .models import (
    Account, JournalEntry, JournalLine, Invoice, InvoiceLine, Payment,
    PaymentApplication, CreditNote, CreditApplication, Bill, BillLine,
    BillPayment, BillPaymentApplication, Budget, Reconciliation,
)


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "type", "is_bank", "is_active")
    list_filter = ("type", "is_bank", "is_active")
    search_fields = ("code", "name")


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_no", "date", "source", "memo", "posted")
    list_filter = ("source", "posted")
    search_fields = ("entry_no", "memo", "reference")
    inlines = [JournalLineInline]


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "number", "customer", "date", "due_date", "status", "show_in_ui"
    )
    list_editable = ("show_in_ui",)
    list_filter = ("status", "show_in_ui")
    search_fields = ("number", "customer__name")
    inlines = [InvoiceLineInline]


class BillLineInline(admin.TabularInline):
    model = BillLine
    extra = 0


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ("number", "supplier", "date", "due_date", "status")
    list_filter = ("status",)
    inlines = [BillLineInline]


admin.site.register(Payment)
admin.site.register(CreditNote)
admin.site.register(BillPayment)
admin.site.register(Budget)
admin.site.register(Reconciliation)
