from django.contrib import admin
from .models import DeliveryConfirmation


@admin.register(DeliveryConfirmation)
class DeliveryConfirmationAdmin(admin.ModelAdmin):
    list_display = ("order", "delivered_at", "received_by", "delivered_by")
    search_fields = ("order__order_no", "received_by")
