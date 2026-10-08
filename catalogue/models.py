from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            i = 1
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def active_product_count(self):
        return self.products.filter(is_active=True).count()


class Product(models.Model):
    class Unit(models.TextChoices):
        PIECE = "pcs", "Piece(s)"
        BOX = "box", "Box"
        CASE = "case", "Case"
        KG = "kg", "Kilogram"
        GRAM = "g", "Gram"
        LITRE = "l", "Litre"
        ML = "ml", "Millilitre"
        PACK = "pack", "Pack"
        DOZEN = "dozen", "Dozen"
        BOTTLE = "bottle", "Bottle"

    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=200)
    sku = models.CharField("Product Code / SKU", max_length=60, unique=True)
    brand = models.CharField(max_length=80, blank=True)
    image = models.ImageField(
        upload_to="products/", blank=True, null=True,
        help_text="Product photo — PNG, JPG or animated GIF.")
    long_description = models.TextField(
        blank=True, help_text="Full description shown on the product detail page.")
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.PIECE)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_price = models.DecimalField(
        "Cost Price", max_digits=12, decimal_places=2, default=0,
        help_text="Purchase cost per unit — used for inventory valuation.",
    )
    stock_qty = models.DecimalField(
        "Available Quantity / Stock", max_digits=12, decimal_places=2,
        default=0, help_text="Optional. Leave as 0 if stock is not tracked.",
    )
    reorder_point = models.DecimalField(
        "Reorder point", max_digits=12, decimal_places=2, default=0,
        help_text="Flag for reorder when stock reaches this level (0 = no alert).",
    )
    track_stock = models.BooleanField(default=False)
    damaged_qty = models.DecimalField(
        "Damaged / written-off stock", max_digits=12, decimal_places=2, default=0,
        help_text="Cumulative units returned damaged and written off (not sellable).",
    )
    is_perishable = models.BooleanField(
        default=False,
        help_text="Perishable item (e.g. vegetables). Stock is tracked in dated "
                  "batches and sold earliest-expiry-first (FEFO).")
    expiry_alert_days = models.PositiveIntegerField(
        default=7,
        help_text="Send an expiry alert this many days before a batch expires.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["sku"]), models.Index(fields=["name"])]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def unit_label(self):
        return self.get_unit_display()

    @property
    def low_stock(self):
        return self.track_stock and self.stock_qty <= 10

    @property
    def out_of_stock(self):
        return self.track_stock and self.stock_qty <= 0

    @property
    def needs_reorder(self):
        return (self.track_stock and self.reorder_point
                and self.stock_qty <= self.reorder_point)

    @property
    def stock_value(self):
        return (self.stock_qty * self.cost_price)

    def similar_products(self, limit=8):
        return (Product.objects.filter(category=self.category, is_active=True)
                .exclude(pk=self.pk)[:limit])

    # --- batch (FEFO) helpers for perishable products ------------------
    def active_batches(self):
        """Batches with stock left, earliest-expiry first (nulls last), then oldest."""
        return (self.batches.filter(qty_remaining__gt=0)
                .order_by(F("expiry_date").asc(nulls_last=True), "received_date", "id"))

    def batch_stock(self):
        return sum((b.qty_remaining for b in self.batches.all()), Decimal("0"))

    def add_batch(self, qty, expiry=None, received_date=None, supplier=None,
                  note="", user=None):
        """Receive a dated batch of stock."""
        qty = Decimal(str(qty))
        return StockBatch.objects.create(
            product=self, qty_received=qty, qty_remaining=qty,
            expiry_date=expiry, received_date=received_date or timezone.localdate(),
            supplier=supplier, note=note, created_by=user)

    def consume_fefo(self, qty):
        """Deplete `qty` from batches, earliest-expiry first. Returns allocations."""
        qty = Decimal(str(qty))
        taken = []
        for batch in list(self.active_batches()):
            if qty <= 0:
                break
            use = min(batch.qty_remaining, qty)
            batch.qty_remaining -= use
            batch.save(update_fields=["qty_remaining"])
            taken.append((batch, use))
            qty -= use
        # if qty still > 0 the product was oversold; stock simply goes to what's left
        return taken

    @property
    def nearest_expiry(self):
        b = self.active_batches().exclude(expiry_date=None).first()
        return b.expiry_date if b else None

    def adjust_stock(self, change, kind, order=None, user=None, note="", expiry=None):
        """Apply a signed change to stock and record a ledger entry.

        For perishable products stock lives in dated batches: outgoing quantities
        deplete earliest-expiry-first (FEFO); incoming quantities create a batch
        (with an expiry date when one is supplied).
        """
        if not self.track_stock:
            return None
        change = Decimal(str(change))
        if self.is_perishable:
            if change < 0:
                self.consume_fefo(-change)
            elif change > 0:
                self.add_batch(change, expiry=expiry, note=note, user=user)
            self.stock_qty = self.batch_stock()
        else:
            self.stock_qty = self.stock_qty + change
        self.save(update_fields=["stock_qty"])
        mv = StockMovement.objects.create(
            product=self, order=order, kind=kind, change=change,
            balance_after=self.stock_qty, created_by=user, note=note,
        )
        # Accounts linkage: a damage / write-off reduces the Inventory Asset
        # and books Inventory Shrinkage. Best-effort — never block the movement.
        if kind == StockMovement.Kind.DAMAGED and change < 0:
            try:
                from accounting import services as _acc
                _acc.write_off_inventory(self, qty=abs(change), user=user, reference=note)
            except Exception:
                pass
        return mv


class ProductSpec(models.Model):
    """Flexible specification field for a product (e.g. Power = 500W)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="specs")
    label = models.CharField(max_length=80)
    value = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.product.sku}: {self.label} = {self.value}"


# Common hardware / power-tool specification presets (from supplier catalogues
# such as DYLLU). Each is (label, placeholder, icon-key). The icon-key maps to
# an SVG on the product detail page so specs render as labelled tiles.
COMMON_SPECS = [
    ("Power", "e.g. 650 W", "power"),
    ("Voltage", "e.g. 220-240V~ / 110-120V~", "voltage"),
    ("No-load Speed", "e.g. 0-3000 /min", "speed"),
    ("Chuck Capacity", 'e.g. 13 mm (1/2")', "chuck"),
    ("Rotation", "e.g. Forward / Reverse", "rotation"),
    ("Impact Rate", "e.g. 0-48000 bpm", "impact"),
    ("Max Drilling (Steel)", "e.g. 13 mm", "drill"),
    ("Max Drilling (Wood)", "e.g. 30 mm", "drill"),
    ("Max Drilling (Concrete)", "e.g. 16 mm", "drill"),
    ("Frequency", "e.g. 50/60 Hz", "frequency"),
    ("Weight", "e.g. 1.8 kg", "weight"),
    ("Cable Length", "e.g. 3 m", "cable"),
    ("Battery", "e.g. 18V Li-ion", "battery"),
    ("Spindle Thread", "e.g. M14", "thread"),
    ("Warranty", "e.g. 12 months", "warranty"),
]


class PriceBreak(models.Model):
    """Quantity-break pricing: unit price when ordering >= min_qty."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_breaks")
    min_qty = models.DecimalField(max_digits=12, decimal_places=2)
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["product", "min_qty"]
        unique_together = ("product", "min_qty")

    def __str__(self):
        return f"{self.product.sku}: >= {self.min_qty} @ {self.price}"


class CustomerPrice(models.Model):
    """Customer-specific fixed unit price for a product (overrides list price)."""
    customer = models.ForeignKey("orders.Customer", on_delete=models.CASCADE,
                                 related_name="prices")
    product = models.ForeignKey(Product, on_delete=models.CASCADE,
                                related_name="customer_prices")
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["customer", "product"]
        unique_together = ("customer", "product")

    def __str__(self):
        return f"{self.customer} · {self.product.sku} @ {self.price}"


def resolve_price(product, customer=None, qty=1):
    """Best unit price: customer override > quantity break > list price."""
    from decimal import Decimal
    qty = Decimal(str(qty or 1))
    if customer is not None:
        cp = product.customer_prices.filter(customer=customer).first()
        if cp:
            return cp.price
    best = None
    for br in product.price_breaks.all():
        if qty >= br.min_qty and (best is None or br.min_qty > best.min_qty):
            best = br
    if best:
        return best.price
    return product.selling_price


class StockMovement(models.Model):
    """Immutable ledger of every stock change (out, return, restock, adjust)."""

    class Kind(models.TextChoices):
        ORDER_OUT = "order_out", "Order placed (out)"
        RETURN_IN = "return_in", "Return to stock (in)"
        DAMAGED = "damaged", "Damaged / write-off"
        RESTOCK = "restock", "Restock (in)"
        ADJUST = "adjust", "Manual adjustment"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="movements")
    order = models.ForeignKey(
        "orders.Order", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_movements",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    change = models.DecimalField(max_digits=12, decimal_places=2,
                                 help_text="Signed: negative = out, positive = in.")
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product.sku}: {self.change} ({self.get_kind_display()})"


class StockBatch(models.Model):
    """A dated lot of a perishable product. Sold earliest-expiry-first (FEFO)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    received_date = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField(null=True, blank=True)
    qty_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    qty_remaining = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    supplier = models.ForeignKey(
        "inventory.Supplier", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="stock_batches")
    note = models.CharField(max_length=200, blank=True)
    alerted_at = models.DateField(
        null=True, blank=True,
        help_text="Last date an expiry alert was emailed for this batch.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["expiry_date", "received_date", "id"]
        verbose_name_plural = "Stock batches"

    def __str__(self):
        exp = self.expiry_date.isoformat() if self.expiry_date else "no expiry"
        return f"{self.product.sku}: {self.qty_remaining} left (exp {exp})"

    @property
    def is_active(self):
        return self.qty_remaining > 0

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self):
        d = self.days_to_expiry
        return d is not None and d < 0

    @property
    def is_expiring_soon(self):
        d = self.days_to_expiry
        if d is None:
            return False
        return 0 <= d <= (self.product.expiry_alert_days or 7)
