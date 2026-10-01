from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Supplier(models.Model):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def po_count(self):
        return self.purchase_orders.count()


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ORDERED = "ordered", "Ordered"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    po_no = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    order_date = models.DateField(default=timezone.now)
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="pos_created",
    )
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pos_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.po_no

    def save(self, *args, **kwargs):
        if not self.po_no:
            self.po_no = self._generate_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_no():
        year = timezone.now().strftime("%y")
        prefix = f"PO-{year}-"
        last = PurchaseOrder.objects.filter(po_no__startswith=prefix).order_by("-po_no").first()
        seq = 1
        if last:
            try:
                seq = int(last.po_no.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = PurchaseOrder.objects.count() + 1
        return f"{prefix}{seq:04d}"

    @property
    def total_cost(self):
        return sum((l.line_cost for l in self.lines.all()), Decimal("0.00"))

    @property
    def total_qty(self):
        return sum((l.qty_ordered for l in self.lines.all()), Decimal("0"))

    @property
    def is_received(self):
        return self.status == self.Status.RECEIVED

    def receive(self, user=None, received_map=None):
        """Add received quantities into stock (once)."""
        if self.status == self.Status.RECEIVED:
            return
        from catalogue.models import StockMovement
        for line in self.lines.select_related("product"):
            qty = line.qty_ordered
            if received_map and str(line.id) in received_map:
                qty = received_map[str(line.id)]
            if qty and line.product:
                line.qty_received = qty
                line.save(update_fields=["qty_received"])
                if line.product.track_stock:
                    line.product.adjust_stock(
                        qty, StockMovement.Kind.RESTOCK, user=user,
                        note=f"{self.po_no} — goods received",
                    )
                # keep cost price fresh from the last purchase
                if line.unit_cost:
                    line.product.cost_price = line.unit_cost
                    line.product.save(update_fields=["cost_price"])
        self.status = self.Status.RECEIVED
        self.received_at = timezone.now()
        self.received_by = user
        self.save(update_fields=["status", "received_at", "received_by"])


class PurchaseOrderLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalogue.Product", on_delete=models.PROTECT)
    qty_ordered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    qty_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product} × {self.qty_ordered}"

    @property
    def line_cost(self):
        return (self.qty_ordered * self.unit_cost).quantize(Decimal("0.01"))
