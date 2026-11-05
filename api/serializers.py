"""DRF serializers for the UDL Belize mobile API."""
from rest_framework import serializers

from catalogue.models import Category, Product, ProductSpec
from orders.models import Customer, Order, OrderItem, OrderStatusLog


def _abs(request, f):
    if not f:
        return ""
    url = f.url
    return request.build_absolute_uri(url) if request else url


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    initials = serializers.CharField()
    role = serializers.CharField()
    role_label = serializers.SerializerMethodField()
    email = serializers.EmailField()
    phone = serializers.CharField()
    access_perms = serializers.SerializerMethodField()

    def get_role_label(self, obj):
        return obj.get_role_display()

    def get_access_perms(self, obj):
        # Effective permissions (admins get everything) so the app can
        # show/hide features per user.
        return obj.effective_perms


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug")


class ProductSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)
    unit_label = serializers.CharField(source="get_unit_display", read_only=True)

    class Meta:
        model = Product
        fields = ("id", "name", "sku", "brand", "category", "category_name",
                  "unit", "unit_label", "selling_price", "stock_qty",
                  "track_stock", "is_perishable", "nearest_expiry", "taxable", "image")

    def get_image(self, obj):
        return _abs(self.context.get("request"), obj.image)


class ProductSpecSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSpec
        fields = ("label", "value")


class ProductDetailSerializer(ProductSerializer):
    specs = ProductSpecSerializer(many=True, read_only=True)
    similar = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + ("long_description", "specs", "similar")

    def get_similar(self, obj):
        req = self.context.get("request")
        out = []
        for sp in obj.similar_products(limit=6):
            out.append({
                "id": sp.pk, "name": sp.name, "sku": sp.sku,
                "selling_price": float(sp.selling_price),
                "image": _abs(req, sp.image),
            })
        return out


class CustomerSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)
    order_count = serializers.IntegerField(read_only=True)
    invoice_count = serializers.IntegerField(read_only=True)
    invoice_total = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ("id", "name", "company_name", "contact_person", "mobile",
                  "email", "billing_address", "delivery_address", "tax_id",
                  "notes", "label", "order_count", "invoice_count",
                  "invoice_total", "can_delete")
        read_only_fields = ("id",)

    def get_invoice_total(self, obj):
        """Sum of every non-void invoice billed to this customer (manual + order)."""
        from decimal import Decimal
        try:
            from accounting.models import Invoice
            tot = sum((inv.total for inv in Invoice.objects.filter(customer=obj)
                       .exclude(status="void")), Decimal("0.00"))
            return float(tot)
        except Exception:
            return 0.0

    def get_can_delete(self, obj):
        """A customer can be deleted only when they have no orders and no invoices."""
        return obj.order_count == 0 and obj.invoice_count == 0


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    image = serializers.SerializerMethodField()
    taxable = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ("id", "product", "product_name", "sku", "unit",
                  "unit_price", "quantity", "line_discount_percent",
                  "line_total", "note", "taxable", "image")

    def get_image(self, obj):
        req = self.context.get("request")
        return _abs(req, obj.product.image) if obj.product_id and obj.product.image else ""

    def get_taxable(self, obj):
        return bool(getattr(getattr(obj, "product", None), "taxable", True)) if obj.product_id else True


class OrderListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.__str__", read_only=True)
    salesperson_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_items = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Order
        fields = ("id", "order_no", "customer", "customer_name", "salesperson_name",
                  "status", "status_label", "total", "total_items", "created_at")

    def get_salesperson_name(self, obj):
        return obj.salesperson.display_name if obj.salesperson_id else ""


class StatusLogSerializer(serializers.ModelSerializer):
    by = serializers.SerializerMethodField()

    class Meta:
        model = OrderStatusLog
        fields = ("from_status", "to_status", "note", "by", "created_at")

    def get_by(self, obj):
        return obj.changed_by.display_name if getattr(obj, "changed_by_id", None) else ""


class OrderDetailSerializer(OrderListSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    discount_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    progress_percent = serializers.IntegerField(read_only=True)
    logs = serializers.SerializerMethodField()
    # Tax (per-item GST) — mirrors the invoice the customer is billed.
    tax_label = serializers.CharField(read_only=True)
    tax_percent_effective = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)
    taxable_subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    tax_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_with_tax = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    can_edit_lines = serializers.SerializerMethodField()

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + (
            "remarks", "team_lead_remarks", "discount_percent", "subtotal",
            "discount_amount", "tax_label", "tax_percent_effective",
            "taxable_subtotal", "tax_amount", "total_with_tax",
            "progress_percent", "confirmed_at", "completed_at",
            "can_edit_lines", "items", "logs")

    def get_logs(self, obj):
        qs = obj.status_logs.all().order_by("created_at") if hasattr(obj, "status_logs") else []
        return StatusLogSerializer(qs, many=True).data

    def get_can_edit_lines(self, obj):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        if not user:
            return False
        try:
            from orders.views import _can_edit_lines
            return bool(_can_edit_lines(user, obj))
        except Exception:
            return False
