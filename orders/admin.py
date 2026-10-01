from django.contrib import admin
from .models import Customer, Order, OrderItem, OrderStatusLog


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class StatusLogInline(admin.TabularInline):
    model = OrderStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "note", "created_at")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("label", "mobile", "email", "order_count", "created_at")
    search_fields = ("name", "company_name", "mobile", "email")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_no", "customer", "salesperson", "status", "total", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("order_no", "customer__name", "customer__company_name")
    inlines = [OrderItemInline, StatusLogInline]


admin.site.register(OrderStatusLog)
