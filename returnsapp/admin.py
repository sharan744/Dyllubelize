from django.contrib import admin
from .models import Return, ReturnLine, ReturnPhoto


class ReturnLineInline(admin.TabularInline):
    model = ReturnLine
    extra = 0


class ReturnPhotoInline(admin.TabularInline):
    model = ReturnPhoto
    extra = 0


@admin.register(Return)
class ReturnAdmin(admin.ModelAdmin):
    list_display = ("rma_no", "order", "reason", "status", "good_qty",
                    "damaged_qty", "created_at")
    list_filter = ("status", "reason", "created_at")
    search_fields = ("rma_no", "order__order_no")
    inlines = [ReturnLineInline, ReturnPhotoInline]
