from django.contrib import admin
from .models import Supplier, PurchaseOrder, PurchaseOrderLine


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "phone", "email", "is_active")
    search_fields = ("name", "contact_person")
    list_filter = ("is_active",)


class POLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("po_no", "supplier", "status", "order_date", "total_cost")
    list_filter = ("status", "order_date")
    search_fields = ("po_no", "supplier__name")
    inlines = [POLineInline]
