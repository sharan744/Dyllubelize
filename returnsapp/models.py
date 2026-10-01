from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Return(models.Model):
    """A returns / RMA record for goods coming back from a customer."""

    class Reason(models.TextChoices):
        DAMAGED = "damaged", "Damaged in transit"
        EXPIRED = "expired", "Expired / spoiled (rotten)"
        WRONG_ITEM = "wrong_item", "Wrong item delivered"
        SHORT = "short", "Short / over shipped"
        NOT_NEEDED = "not_needed", "No longer needed"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    rma_no = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    order = models.ForeignKey(
        "orders.Order", on_delete=models.PROTECT, related_name="returns"
    )
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.DAMAGED)
    reason_note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="returns_created",
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="returns_processed",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.rma_no

    def save(self, *args, **kwargs):
        if not self.rma_no:
            self.rma_no = self._generate_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_no():
        year = timezone.now().strftime("%y")
        prefix = f"RMA-{year}-"
        last = Return.objects.filter(rma_no__startswith=prefix).order_by("-rma_no").first()
        seq = 1
        if last:
            try:
                seq = int(last.rma_no.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = Return.objects.count() + 1
        return f"{prefix}{seq:04d}"

    # --- Totals ---
    @property
    def customer(self):
        return self.order.customer

    @property
    def total_qty(self):
        return sum((l.quantity for l in self.lines.all()), Decimal("0"))

    @property
    def good_qty(self):
        return sum((l.good_qty for l in self.lines.all()), Decimal("0"))

    @property
    def damaged_qty(self):
        return sum((l.damaged_qty for l in self.lines.all()), Decimal("0"))

    @property
    def total_value(self):
        return sum((l.line_value for l in self.lines.all()), Decimal("0.00"))

    @property
    def damaged_value(self):
        return sum((l.damaged_value for l in self.lines.all()), Decimal("0.00"))

    @property
    def restock_value(self):
        return sum((l.good_value for l in self.lines.all()), Decimal("0.00"))

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED

    # --- Processing: apply stock effects once ---
    def process(self, user=None):
        if self.status == self.Status.COMPLETED:
            return
        from catalogue.models import StockMovement
        for line in self.lines.select_related("product"):
            p = line.product
            if not p:
                continue
            if line.good_qty and p.track_stock:
                p.adjust_stock(
                    line.good_qty, StockMovement.Kind.RETURN_IN,
                    order=self.order, user=user,
                    note=f"{self.rma_no} — good units returned to stock",
                )
            if line.damaged_qty:
                # Damaged units do NOT re-enter sellable stock; write them off.
                p.damaged_qty = (p.damaged_qty or Decimal("0")) + line.damaged_qty
                p.save(update_fields=["damaged_qty"])
                if p.track_stock:
                    StockMovement.objects.create(
                        product=p, order=self.order, kind=StockMovement.Kind.DAMAGED,
                        change=Decimal("0"), balance_after=p.stock_qty, created_by=user,
                        note=f"{self.rma_no} — {line.damaged_qty} unit(s) written off (damaged)",
                    )
        self.status = self.Status.COMPLETED
        self.processed_by = user
        self.processed_at = timezone.now()
        self.save(update_fields=["status", "processed_by", "processed_at"])


class ReturnLine(models.Model):
    ret = models.ForeignKey(Return, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalogue.Product", on_delete=models.PROTECT)
    product_name = models.CharField(max_length=200)
    sku = models.CharField(max_length=60)
    unit = models.CharField(max_length=20, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    good_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    damaged_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product_name}: {self.quantity} back"

    @property
    def quantity(self):
        return (self.good_qty or 0) + (self.damaged_qty or 0)

    @property
    def line_value(self):
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    @property
    def good_value(self):
        return (self.unit_price * self.good_qty).quantize(Decimal("0.01"))

    @property
    def damaged_value(self):
        return (self.unit_price * self.damaged_qty).quantize(Decimal("0.01"))


class ReturnPhoto(models.Model):
    ret = models.ForeignKey(Return, on_delete=models.CASCADE, related_name="photos")
    image = models.FileField(upload_to="returns/")
    caption = models.CharField(max_length=200, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Photo for {self.ret.rma_no}"
