from django.conf import settings
from django.db import models
from django.utils import timezone


class Dispatch(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        DISPATCHED = "dispatched", "Dispatched"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    dispatch_no = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    orders = models.ManyToManyField("orders.Order", related_name="dispatches")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)

    # Vehicle & driver
    vehicle_details = models.CharField("Vehicle Details", max_length=200, blank=True)
    driver_name = models.CharField(max_length=150, blank=True)
    driver_contact = models.CharField("Driver Contact Number", max_length=30, blank=True)

    dispatch_date = models.DateField(default=timezone.now)
    expected_delivery_date = models.DateField(null=True, blank=True)
    special_instructions = models.TextField("Special Delivery Instructions", blank=True)
    remarks = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="dispatches_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Dispatches"

    def __str__(self):
        return self.dispatch_no

    def save(self, *args, **kwargs):
        if not self.dispatch_no:
            self.dispatch_no = self._generate_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_no():
        year = timezone.now().strftime("%y")
        prefix = f"DSP-{year}-"
        last = (
            Dispatch.objects.filter(dispatch_no__startswith=prefix)
            .order_by("-dispatch_no")
            .first()
        )
        seq = 1
        if last:
            try:
                seq = int(last.dispatch_no.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = Dispatch.objects.count() + 1
        return f"{prefix}{seq:04d}"

    @property
    def order_count(self):
        return self.orders.count()

    @property
    def total_items(self):
        total = 0
        for order in self.orders.all():
            total += sum((i.quantity for i in order.items.all()), 0)
        return total

    @property
    def customers(self):
        return [o.customer for o in self.orders.all()]

    @property
    def is_multi_stop(self):
        return self.order_count > 1
