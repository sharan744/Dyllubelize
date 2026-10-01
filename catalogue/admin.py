from django.contrib import admin
from .models import (Category, Product, StockMovement, PriceBreak,
                     CustomerPrice, ProductSpec)


class PriceBreakInline(admin.TabularInline):
    model = PriceBreak
    extra = 1


class ProductSpecInline(admin.TabularInline):
    model = ProductSpec
    extra = 3


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "active_product_count", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "category", "unit", "selling_price", "stock_qty", "is_active")
    list_filter = ("category", "is_active", "unit", "track_stock")
    search_fields = ("name", "sku")
    list_editable = ("selling_price", "is_active")
    inlines = [ProductSpecInline, PriceBreakInline]


@admin.register(CustomerPrice)
class CustomerPriceAdmin(admin.ModelAdmin):
    list_display = ("customer", "product", "price")
    list_filter = ("customer",)
    search_fields = ("customer__name", "customer__company_name", "product__name", "product__sku")
    autocomplete_fields = ()


@admin.register(PriceBreak)
class PriceBreakAdmin(admin.ModelAdmin):
    list_display = ("product", "min_qty", "price")
    search_fields = ("product__name", "product__sku")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "kind", "change", "balance_after",
                    "order", "created_by")
    list_filter = ("kind", "created_at")
    search_fields = ("product__name", "product__sku", "order__order_no")
    readonly_fields = ("product", "order", "kind", "change", "balance_after",
                       "note", "created_by", "created_at")
