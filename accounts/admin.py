from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "display_name", "role", "email", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = UserAdmin.fieldsets + (
        ("Role & Contact", {"fields": ("role", "phone", "incentive_percent")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Role & Contact", {"fields": ("role", "phone", "first_name", "last_name", "email")}),
    )
