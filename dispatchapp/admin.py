from django.contrib import admin
from .models import Dispatch


@admin.register(Dispatch)
class DispatchAdmin(admin.ModelAdmin):
    list_display = ("dispatch_no", "status", "driver_name", "vehicle_details",
                    "dispatch_date", "order_count")
    list_filter = ("status", "dispatch_date")
    search_fields = ("dispatch_no", "driver_name", "vehicle_details")
    filter_horizontal = ("orders",)
