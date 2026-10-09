"""
Extended DRF serializers for full-parity mobile API:
suppliers, purchase orders, inventory/stock, returns, dispatches,
deliveries, and accounting (invoices, bills, payments, accounts).
"""
from rest_framework import serializers

from inventory.models import Supplier, PurchaseOrder, PurchaseOrderLine
from catalogue.models import StockMovement, StockBatch, Product
from returnsapp.models import Return, ReturnLine
from dispatchapp.models import Dispatch
from delivery.models import DeliveryConfirmation
from accounting.models import (
    Account, Invoice, InvoiceLine, Bill, BillLine, Payment, JournalEntry, JournalLine,
)


def _abs(request, f):
    if not f:
        return ""
    try:
        url = f.url
    except Exception:
        return ""
    return request.build_absolute_uri(url) if request else url


# ----------------------------------------------------------- suppliers
class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ("id", "name", "contact_person", "phone", "email",
                  "address", "notes", "is_active")
        read_only_fields = ("id",)


# ----------------------------------------------------- purchase orders
class POLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLine
        fields = ("id", "product", "product_name", "sku", "qty_ordered",
                  "qty_received", "unit_cost", "line_total")

    def get_line_total(self, obj):
        return float((obj.qty_received or obj.qty_ordered) * obj.unit_cost)


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    total_cost = serializers.SerializerMethodField()
    total_qty = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = ("id", "po_no", "supplier", "supplier_name", "status",
                  "status_label", "order_date", "expected_date",
                  "total_cost", "total_qty", "created_at")

    def get_total_cost(self, obj):
        return float(obj.total_cost)

    def get_total_qty(self, obj):
        return float(obj.total_qty)


class PurchaseOrderDetailSerializer(PurchaseOrderListSerializer):
    lines = POLineSerializer(many=True, read_only=True)
    received_at = serializers.DateTimeField(read_only=True)

    class Meta(PurchaseOrderListSerializer.Meta):
        fields = PurchaseOrderListSerializer.Meta.fields + ("notes", "received_at", "lines")


# ------------------------------------------------------- inventory/stock
class InventoryProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    unit_label = serializers.CharField(source="get_unit_display", read_only=True)
    low_stock = serializers.BooleanField(read_only=True)
    out_of_stock = serializers.BooleanField(read_only=True)
    needs_reorder = serializers.BooleanField(read_only=True)
    stock_value = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ("id", "name", "sku", "brand", "category_name", "unit", "unit_label",
                  "stock_qty", "reorder_point", "cost_price", "selling_price",
                  "track_stock", "is_perishable", "nearest_expiry",
                  "low_stock", "out_of_stock", "needs_reorder", "stock_value", "image")

    def get_stock_value(self, obj):
        return float(obj.stock_value)

    def get_image(self, obj):
        return _abs(self.context.get("request"), obj.image)


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    by = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = ("id", "product", "product_name", "sku", "kind", "kind_label",
                  "change", "balance_after", "note", "by", "created_at")

    def get_by(self, obj):
        return obj.created_by.display_name if getattr(obj, "created_by_id", None) else ""


class StockBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockBatch
        fields = ("id", "product", "product_name", "sku", "received_date",
                  "expiry_date", "qty_received", "qty_remaining", "note")


# ----------------------------------------------------------- returns
class ReturnLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnLine
        fields = ("id", "product", "product_name", "sku", "unit", "unit_price",
                  "good_qty", "damaged_qty", "note")


class ReturnListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)
    order_no = serializers.CharField(source="order.order_no", read_only=True)
    customer_name = serializers.SerializerMethodField()
    total_qty = serializers.SerializerMethodField()
    total_value = serializers.SerializerMethodField()

    class Meta:
        model = Return
        fields = ("id", "rma_no", "order", "order_no", "customer_name", "reason",
                  "reason_label", "status", "status_label", "total_qty",
                  "total_value", "created_at")

    def get_customer_name(self, obj):
        c = obj.customer
        return str(c) if c else ""

    def get_total_qty(self, obj):
        return float(obj.total_qty)

    def get_total_value(self, obj):
        return float(obj.total_value)


class ReturnDetailSerializer(ReturnListSerializer):
    lines = ReturnLineSerializer(many=True, read_only=True)
    good_qty = serializers.SerializerMethodField()
    damaged_qty = serializers.SerializerMethodField()

    class Meta(ReturnListSerializer.Meta):
        fields = ReturnListSerializer.Meta.fields + (
            "reason_note", "notes", "good_qty", "damaged_qty", "lines")

    def get_good_qty(self, obj):
        return float(obj.good_qty)

    def get_damaged_qty(self, obj):
        return float(obj.damaged_qty)


# ---------------------------------------------------------- dispatches
class DispatchSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    order_nos = serializers.SerializerMethodField()

    class Meta:
        model = Dispatch
        fields = ("id", "dispatch_no", "status", "status_label", "vehicle_details",
                  "driver_name", "driver_contact", "dispatch_date",
                  "expected_delivery_date", "special_instructions", "remarks",
                  "order_nos", "created_at")

    def get_order_nos(self, obj):
        return list(obj.orders.values_list("order_no", flat=True))


# ---------------------------------------------------------- deliveries
class DeliverySerializer(serializers.ModelSerializer):
    order_no = serializers.CharField(source="order.order_no", read_only=True)
    customer_name = serializers.SerializerMethodField()
    delivered_by_name = serializers.SerializerMethodField()
    pod_file = serializers.SerializerMethodField()

    class Meta:
        model = DeliveryConfirmation
        fields = ("id", "order", "order_no", "customer_name", "delivered_at",
                  "delivered_by_name", "received_by", "signature_name",
                  "remarks", "pod_file", "created_at")

    def get_customer_name(self, obj):
        return str(obj.order.customer) if obj.order_id and obj.order.customer_id else ""

    def get_delivered_by_name(self, obj):
        return obj.delivered_by.display_name if getattr(obj, "delivered_by_id", None) else ""

    def get_pod_file(self, obj):
        return _abs(self.context.get("request"), obj.pod_file)


# ---------------------------------------------------------- accounting
class AccountSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source="get_type_display", read_only=True)
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = ("id", "code", "name", "type", "type_label", "is_bank", "balance")

    def get_balance(self, obj):
        try:
            return float(obj.balance() + obj.opening_balance)
        except Exception:
            return 0.0


class InvoiceLineSerializer(serializers.ModelSerializer):
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLine
        fields = ("id", "description", "quantity", "unit_price", "line_total")

    def get_line_total(self, obj):
        return float(obj.quantity * obj.unit_price)


class InvoiceListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.__str__", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    total = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invoice
        fields = ("id", "number", "customer", "customer_name", "date", "due_date",
                  "status", "status_label", "total", "balance", "is_overdue")

    def get_total(self, obj):
        return float(obj.total)

    def get_balance(self, obj):
        return float(obj.balance)


class InvoiceDetailSerializer(InvoiceListSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    tax = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()

    class Meta(InvoiceListSerializer.Meta):
        fields = InvoiceListSerializer.Meta.fields + (
            "memo", "tax_percent", "subtotal", "tax", "amount_paid", "lines")

    def get_subtotal(self, obj):
        return float(obj.subtotal)

    def get_tax(self, obj):
        return float(obj.tax)

    def get_amount_paid(self, obj):
        return float(obj.amount_paid)


class BillListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    total = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = ("id", "number", "supplier", "supplier_name", "date", "due_date",
                  "status", "status_label", "total", "balance")

    def get_total(self, obj):
        return float(obj.total)

    def get_balance(self, obj):
        return float(obj.balance)


class BillLineSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = BillLine
        fields = ("id", "description", "account_name", "amount")


class BillDetailSerializer(BillListSerializer):
    lines = BillLineSerializer(many=True, read_only=True)
    amount_paid = serializers.SerializerMethodField()

    class Meta(BillListSerializer.Meta):
        fields = BillListSerializer.Meta.fields + ("memo", "amount_paid", "lines")

    def get_amount_paid(self, obj):
        return float(obj.amount_paid)


class PaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.__str__", read_only=True)
    method_label = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = Payment
        fields = ("id", "number", "customer", "customer_name", "date", "method",
                  "method_label", "amount", "reference", "memo")
