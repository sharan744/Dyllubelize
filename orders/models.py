from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class Customer(models.Model):
    name = models.CharField("Customer Name", max_length=200)
    company_name = models.CharField("Company / Shop Name", max_length=200, blank=True)
    contact_person = models.CharField(max_length=150, blank=True)
    mobile = models.CharField("Mobile Number", max_length=30)
    email = models.EmailField("Email ID", blank=True)
    billing_address = models.TextField(blank=True)
    delivery_address = models.TextField(blank=True)
    tax_id = models.CharField(
        "Tax ID (RFC / GST)", max_length=40, blank=True,
        help_text="RFC for Mexico, or GST / other tax registration if applicable.",
    )
    notes = models.TextField("Other Information", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="customers_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["mobile"])]

    def __str__(self):
        return self.company_name or self.name

    @property
    def label(self):
        if self.company_name:
            return f"{self.company_name} — {self.name}"
        return self.name

    @property
    def order_count(self):
        return self.orders.count()


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    TEAM_LEAD_REVIEW = "review", "Team Lead Review"
    CONFIRMED = "confirmed", "Confirmed"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready for Dispatch"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected / Returned"
    CANCELLED = "cancelled", "Cancelled"


# Ordered pipeline used for progress indicators
STATUS_PIPELINE = [
    OrderStatus.DRAFT,
    OrderStatus.SUBMITTED,
    OrderStatus.TEAM_LEAD_REVIEW,
    OrderStatus.CONFIRMED,
    OrderStatus.PROCESSING,
    OrderStatus.READY,
    OrderStatus.DISPATCHED,
    OrderStatus.DELIVERED,
    OrderStatus.COMPLETED,
]


class Order(models.Model):
    order_no = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="orders_created",
    )
    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.DRAFT, db_index=True
    )
    remarks = models.TextField("Remarks / Special Instructions", blank=True)
    team_lead_remarks = models.TextField(blank=True)

    # discount applied on the whole order (percentage)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders_confirmed",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # True once this order's quantities have been taken out of stock.
    stock_committed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_no

    def save(self, *args, **kwargs):
        if not self.order_no:
            self.order_no = self._generate_order_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_order_no():
        year = timezone.now().strftime("%y")
        prefix = f"ORD-{year}-"
        last = (
            Order.objects.filter(order_no__startswith=prefix)
            .order_by("-order_no")
            .first()
        )
        seq = 1
        if last:
            try:
                seq = int(last.order_no.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = Order.objects.count() + 1
        return f"{prefix}{seq:04d}"

    # --- Money ---
    @property
    def subtotal(self):
        return sum((i.line_total for i in self.items.all()), Decimal("0.00"))

    @property
    def discount_amount(self):
        return (self.subtotal * self.discount_percent / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def total(self):
        return (self.subtotal - self.discount_amount).quantize(Decimal("0.01"))

    @property
    def total_cost(self):
        return sum((i.line_cost_total for i in self.items.all()), Decimal("0.00"))

    @property
    def margin(self):
        return (self.total - self.total_cost).quantize(Decimal("0.01"))

    @property
    def margin_percent(self):
        return (self.margin / self.total * Decimal("100")).quantize(Decimal("0.1")) if self.total else Decimal("0")

    @property
    def total_items(self):
        return sum((i.quantity for i in self.items.all()), Decimal("0"))

    @property
    def distinct_items(self):
        return self.items.count()

    # --- Status helpers ---
    @property
    def status_index(self):
        try:
            return STATUS_PIPELINE.index(self.status)
        except ValueError:
            return -1

    @property
    def progress_percent(self):
        idx = self.status_index
        if idx < 0:
            return 0
        return int(round(idx / (len(STATUS_PIPELINE) - 1) * 100))

    @property
    def is_open(self):
        return self.status not in (
            OrderStatus.COMPLETED, OrderStatus.REJECTED, OrderStatus.CANCELLED
        )

    def set_status(self, new_status, user=None, note=""):
        old = self.status
        self.status = new_status
        if new_status == OrderStatus.CONFIRMED and not self.confirmed_at:
            self.confirmed_by = user
            self.confirmed_at = timezone.now()
        if new_status == OrderStatus.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()
        self.save()
        OrderStatusLog.objects.create(
            order=self, from_status=old, to_status=new_status,
            changed_by=user, note=note,
        )
        # --- Inventory side effects ---
        if new_status == OrderStatus.SUBMITTED:
            self.commit_stock(user)
        elif new_status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
            self.release_stock(user)

    def commit_stock(self, user=None):
        """Take this order's quantities out of stock (once)."""
        if self.stock_committed:
            return
        from catalogue.models import StockMovement
        for it in self.items.select_related("product"):
            if it.product and it.product.track_stock:
                it.product.adjust_stock(
                    -it.quantity, StockMovement.Kind.ORDER_OUT,
                    order=self, user=user, note=f"Order {self.order_no} placed",
                )
        self.stock_committed = True
        self.save(update_fields=["stock_committed"])

    def release_stock(self, user=None):
        """Return this order's quantities to stock (once)."""
        if not self.stock_committed:
            return
        from catalogue.models import StockMovement
        label = self.get_status_display().lower()
        for it in self.items.select_related("product"):
            if it.product and it.product.track_stock:
                it.product.adjust_stock(
                    it.quantity, StockMovement.Kind.RETURN_IN,
                    order=self, user=user,
                    note=f"Order {self.order_no} {label} — returned to stock",
                )
        self.stock_committed = False
        self.save(update_fields=["stock_committed"])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalogue.Product", on_delete=models.PROTECT)
    # snapshot fields so historical orders stay correct even if catalogue changes
    product_name = models.CharField(max_length=200)
    sku = models.CharField(max_length=60)
    unit = models.CharField(max_length=20)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    line_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"

    def save(self, *args, **kwargs):
        if self.product_id and not self.product_name:
            self.product_name = self.product.name
            self.sku = self.product.sku
            self.unit = self.product.get_unit_display()
            if not self.unit_price:
                self.unit_price = self.product.selling_price
        if self.product_id and not self.unit_cost:
            self.unit_cost = self.product.cost_price or Decimal("0")
        super().save(*args, **kwargs)

    @property
    def line_total(self):
        gross = self.unit_price * self.quantity
        disc = gross * self.line_discount_percent / Decimal("100")
        return (gross - disc).quantize(Decimal("0.01"))

    @property
    def line_cost_total(self):
        return (self.unit_cost * self.quantity).quantize(Decimal("0.01"))

    @property
    def line_margin(self):
        return (self.line_total - self.line_cost_total).quantize(Decimal("0.01"))


class OrderStatusLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_logs")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order.order_no}: {self.from_status} → {self.to_status}"

    @property
    def to_status_label(self):
        return OrderStatus(self.to_status).label if self.to_status in OrderStatus.values else self.to_status
