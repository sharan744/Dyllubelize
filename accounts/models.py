from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    SALES = "sales", "Sales Person"
    TEAM_LEAD = "team_lead", "Team Lead"
    PROCESSING = "processing", "Processing Team"
    DISPATCH = "dispatch", "Dispatch Team"
    DELIVERY = "delivery", "Delivery Team"


class User(AbstractUser):
    """Custom user with a single primary role used for access control."""

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.SALES,
        help_text="Determines what the user can see and do.",
    )
    phone = models.CharField(max_length=20, blank=True)
    incentive_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Overrides the company default incentive % for this salesperson (blank = use default).",
    )

    class Meta:
        ordering = ["first_name", "username"]

    def __str__(self):
        name = self.get_full_name() or self.username
        return f"{name} ({self.get_role_display()})"

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = (self.get_full_name() or self.username).split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return (self.username[:2]).upper()

    # --- Role helpers ---
    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN or self.is_superuser

    @property
    def is_sales(self):
        return self.role == Role.SALES

    @property
    def is_team_lead(self):
        return self.role == Role.TEAM_LEAD

    @property
    def is_processing(self):
        return self.role == Role.PROCESSING

    @property
    def is_dispatch(self):
        return self.role == Role.DISPATCH

    @property
    def is_delivery(self):
        return self.role == Role.DELIVERY

    def can(self, *roles):
        """True if the user's role is in roles (admin can do everything)."""
        return self.is_admin_role or self.role in roles
