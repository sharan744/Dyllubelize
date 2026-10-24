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
    # Goods are purchased in USD; this is the BZD-per-USD rate the user types
    # for this PO (Belize dollar is ~2.00 to the USD; a small premium is common).
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("2.00"))
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
        """Total landed cost (BZD) = sum of each line's final landed cost."""
        return sum((l.line_cost for l in self.lines.all()), Decimal("0.00"))

    # ---- USD → BZD landed-cost model ----
    @property
    def goods_value_usd(self):
        """Supplier invoice value in USD (qty × USD unit price)."""
        return sum((l.line_value_usd for l in self.lines.all()), Decimal("0.00"))

    @property
    def goods_value_bzd(self):
        """Goods converted to BZD at this PO's exchange rate."""
        return (self.goods_value_usd * (self.exchange_rate or Decimal("0"))).quantize(Decimal("0.01"))

    @property
    def total_expenses(self):
        """All PO expenses in BZD (USD expenses converted at the PO rate)."""
        rate = self.exchange_rate or Decimal("0")
        total = Decimal("0.00")
        for e in self.expenses.all():
            total += e.amount_in_bzd(rate)
        return total.quantize(Decimal("0.01"))

    @property
    def expense_ratio(self):
        """How much expenses inflate the landed cost over the goods' BZD value.
        1.00 = no expenses; 1.25 = expenses add 25% on top. Expenses are spread
        across products in proportion to value (matches the supplier-sheet method)."""
        gb = self.goods_value_bzd
        if gb <= 0:
            return Decimal("1.000000000")
        return ((gb + self.total_expenses) / gb).quantize(Decimal("0.000000001"))

    @property
    def landed_multiplier(self):
        """One factor to turn a USD unit price into its landed BZD cost:
        exchange_rate × expense_ratio (the supplier sheet's E29)."""
        return ((self.exchange_rate or Decimal("0")) * self.expense_ratio).quantize(Decimal("0.0001"))

    @property
    def grand_total(self):
        """Full landed value of the PO in BZD = goods (BZD) + all expenses.
        This is the amount the expense ratio is based on."""
        return (self.goods_value_bzd + self.total_expenses).quantize(Decimal("0.01"))

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
                # Update the catalogue from this PO: landed cost always, and the
                # selling price when one was entered on the PO line.
                fields = []
                if line.unit_cost:
                    line.product.cost_price = line.unit_cost
                    fields.append("cost_price")
                if getattr(line, "sell_price", 0) and line.sell_price > 0:
                    line.product.selling_price = line.sell_price
                    fields.append("selling_price")
                if fields:
                    line.product.save(update_fields=fields)
        self.status = self.Status.RECEIVED
        self.received_at = timezone.now()
        self.received_by = user
        self.save(update_fields=["status", "received_at", "received_by"])
        # Link into the accounts (QuickBooks-style): book the received stock as
        # Inventory Asset and raise Accounts Payable to the supplier. Best-effort
        # — a problem here must never block goods receipt.
        try:
            from accounting import services as _acc
            _acc.bill_from_po(self, user=user)
        except Exception:
            pass


class PurchaseOrderLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalogue.Product", on_delete=models.PROTECT)
    qty_ordered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    qty_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Supplier's price per unit in USD (what's on the foreign invoice).
    unit_cost_usd = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    # Final landed cost per unit in BZD (after FX + expense ratio). The user may
    # override the computed value directly. Downstream accounting/stock uses this.
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Reference selling price (BZD) set by admin/sales — display only, not applied.
    sell_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product} × {self.qty_ordered}"

    @property
    def line_value_usd(self):
        return (self.qty_ordered * self.unit_cost_usd).quantize(Decimal("0.01"))

    @property
    def line_cost(self):
        """Total landed cost of the line in BZD."""
        return (self.qty_ordered * self.unit_cost).quantize(Decimal("0.01"))

    @property
    def line_selling(self):
        return (self.qty_ordered * self.sell_price).quantize(Decimal("0.01"))

    @property
    def unit_margin(self):
        return (self.sell_price - self.unit_cost).quantize(Decimal("0.01"))

    @property
    def margin_percent(self):
        """Margin on cost (markup %), mirrors the supplier sheet's (sell−cost)/cost."""
        if self.unit_cost and self.unit_cost > 0:
            return ((self.sell_price - self.unit_cost) / self.unit_cost * Decimal("100")).quantize(Decimal("0.1"))
        return Decimal("0.0")


class PurchaseOrderExpense(models.Model):
    """An extra cost tied to a purchase order (freight, customs, handling, …).
    Entered on the New PO screen alongside the product lines. Each expense is in
    USD or BZD; USD expenses are converted at the PO's exchange rate."""
    class Currency(models.TextChoices):
        BZD = "BZD", "BZD"
        USD = "USD", "USD"

    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="expenses")
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.BZD)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name}: {self.amount} {self.currency}"

    def amount_in_bzd(self, rate):
        """This expense in BZD — converted at `rate` when entered in USD."""
        if self.currency == self.Currency.USD:
            return (self.amount * (rate or Decimal("0"))).quantize(Decimal("0.01"))
        return self.amount.quantize(Decimal("0.01"))

    @property
    def amount_bzd(self):
        """Template-friendly: this expense in BZD using its PO's exchange rate."""
        rate = self.po.exchange_rate if self.po_id else Decimal("1")
        return self.amount_in_bzd(rate)