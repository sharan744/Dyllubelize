"""
Extended mobile API endpoints (full parity):
suppliers, purchase orders, inventory/stock, returns, dispatches,
deliveries, and accounting (invoices, bills, payments, P&L, balance sheet).

All endpoints require authentication (token). Sensitive write/admin areas
check the user's role; reads are available to authenticated staff.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.decorators import api_view
from rest_framework.response import Response

from inventory.models import Supplier, PurchaseOrder, PurchaseOrderLine
from catalogue.models import Product, StockMovement, StockBatch
from returnsapp.models import Return, ReturnLine
from dispatchapp.models import Dispatch
from delivery.models import DeliveryConfirmation
from accounting.models import (
    Account, AccountType, Invoice, Bill, Payment, DocStatus,
)
from .serializers2 import (
    SupplierSerializer, PurchaseOrderListSerializer, PurchaseOrderDetailSerializer,
    InventoryProductSerializer, StockMovementSerializer, StockBatchSerializer,
    ReturnListSerializer, ReturnDetailSerializer, DispatchSerializer,
    DeliverySerializer, AccountSerializer, InvoiceListSerializer,
    InvoiceDetailSerializer, BillListSerializer, BillDetailSerializer,
    PaymentSerializer,
)

Z = Decimal("0")


def _dec(v, default="0"):
    try:
        return Decimal(str(v if v not in (None, "") else default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _admin_or_403(user):
    return user.is_admin_role


# ======================================================== suppliers
@api_view(["GET", "POST"])
def suppliers(request):
    if request.method == "POST":
        ser = SupplierSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=http.HTTP_201_CREATED)
    qs = Supplier.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(contact_person__icontains=q))
    return Response(SupplierSerializer(qs, many=True).data)


# ================================================== purchase orders
@api_view(["GET", "POST"])
def purchase_orders(request):
    if request.method == "POST":
        return _create_po(request)
    qs = PurchaseOrder.objects.select_related("supplier").all()
    st = request.GET.get("status", "")
    if st:
        qs = qs.filter(status=st)
    return Response(PurchaseOrderListSerializer(
        qs[:200], many=True, context={"request": request}).data)


def _create_po(request):
    sup_id = request.data.get("supplier")
    if not sup_id:
        return Response({"detail": "supplier is required."}, status=http.HTTP_400_BAD_REQUEST)
    supplier = get_object_or_404(Supplier, pk=sup_id)
    lines = request.data.get("lines") or []
    po = PurchaseOrder.objects.create(
        supplier=supplier, created_by=request.user,
        status=PurchaseOrder.Status.ORDERED,
        notes=request.data.get("notes", "") or "")
    for ln in lines:
        try:
            product = Product.objects.get(pk=ln.get("product") or ln.get("id"))
        except (Product.DoesNotExist, ValueError, TypeError):
            continue
        PurchaseOrderLine.objects.create(
            po=po, product=product,
            qty_ordered=_dec(ln.get("qty", 1) or 1),
            unit_cost=_dec(ln.get("unit_cost", product.cost_price)))
    if not po.lines.exists():
        po.delete()
        return Response({"detail": "Add at least one line."}, status=http.HTTP_400_BAD_REQUEST)
    return Response(PurchaseOrderDetailSerializer(
        po, context={"request": request}).data, status=http.HTTP_201_CREATED)


@api_view(["GET"])
def po_detail(request, pk):
    po = get_object_or_404(PurchaseOrder.objects.select_related("supplier"), pk=pk)
    return Response(PurchaseOrderDetailSerializer(po, context={"request": request}).data)


@api_view(["POST"])
def po_receive(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    if po.status == PurchaseOrder.Status.RECEIVED:
        return Response({"detail": "Already received."}, status=http.HTTP_400_BAD_REQUEST)
    received_map = request.data.get("received") or None   # {line_id: qty}
    po.receive(user=request.user, received_map=received_map)
    return Response(PurchaseOrderDetailSerializer(po, context={"request": request}).data)


# ======================================================== inventory
@api_view(["GET"])
def inventory_overview(request):
    qs = Product.objects.filter(track_stock=True).select_related("category")
    q = request.GET.get("q", "").strip()
    flt = request.GET.get("filter", "")        # low | reorder | out
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    products = list(qs[:400])
    if flt == "low":
        products = [p for p in products if p.low_stock]
    elif flt == "reorder":
        products = [p for p in products if p.needs_reorder]
    elif flt == "out":
        products = [p for p in products if p.out_of_stock]
    data = InventoryProductSerializer(products, many=True, context={"request": request}).data
    totals = {
        "sku_count": len(products),
        "stock_value": float(sum((p.stock_value for p in products), Z)),
        "low_count": sum(1 for p in products if p.low_stock),
        "out_count": sum(1 for p in products if p.out_of_stock),
    }
    return Response({"products": data, "totals": totals})


@api_view(["GET"])
def stock_movements(request):
    qs = StockMovement.objects.select_related("product", "created_by").all()
    pid = request.GET.get("product")
    if pid:
        qs = qs.filter(product_id=pid)
    return Response(StockMovementSerializer(
        qs[:200], many=True, context={"request": request}).data)


@api_view(["GET"])
def expiring_batches(request):
    days = int(request.GET.get("days", "60") or 60)
    cutoff = timezone.localdate() + timezone.timedelta(days=days)
    qs = (StockBatch.objects.select_related("product")
          .filter(qty_remaining__gt=0, expiry_date__isnull=False,
                  expiry_date__lte=cutoff)
          .order_by("expiry_date"))
    return Response(StockBatchSerializer(qs[:200], many=True,
                                         context={"request": request}).data)


# ========================================================== returns
@api_view(["GET", "POST"])
def returns(request):
    if request.method == "POST":
        return _create_return(request)
    qs = Return.objects.select_related("order").all()
    st = request.GET.get("status", "")
    if st:
        qs = qs.filter(status=st)
    return Response(ReturnListSerializer(qs[:200], many=True).data)


def _create_return(request):
    from orders.models import Order
    order_id = request.data.get("order")
    order = get_object_or_404(Order, pk=order_id) if order_id else None
    if not order:
        return Response({"detail": "order is required."}, status=http.HTTP_400_BAD_REQUEST)
    ret = Return.objects.create(
        order=order, reason=request.data.get("reason", Return.Reason.DAMAGED),
        reason_note=request.data.get("reason_note", "") or "",
        notes=request.data.get("notes", "") or "", created_by=request.user)
    for ln in (request.data.get("lines") or []):
        try:
            product = Product.objects.get(pk=ln.get("product") or ln.get("id"))
        except (Product.DoesNotExist, ValueError, TypeError):
            continue
        ReturnLine.objects.create(
            ret=ret, product=product, product_name=product.name, sku=product.sku,
            unit=product.get_unit_display(), unit_price=_dec(ln.get("unit_price", product.selling_price)),
            good_qty=_dec(ln.get("good_qty", 0)), damaged_qty=_dec(ln.get("damaged_qty", 0)),
            note=str(ln.get("note", ""))[:255])
    if not ret.lines.exists():
        ret.delete()
        return Response({"detail": "Add at least one line."}, status=http.HTTP_400_BAD_REQUEST)
    return Response(ReturnDetailSerializer(ret).data, status=http.HTTP_201_CREATED)


@api_view(["GET"])
def return_detail(request, pk):
    return Response(ReturnDetailSerializer(get_object_or_404(Return, pk=pk)).data)


@api_view(["POST"])
def return_action(request, pk):
    ret = get_object_or_404(Return, pk=pk)
    action = request.data.get("action", "")
    if action == "complete" and hasattr(ret, "complete"):
        ret.complete(user=request.user)
    elif action == "cancel":
        ret.status = Return.Status.CANCELLED
        ret.save(update_fields=["status"])
    else:
        return Response({"detail": f"Unknown action '{action}'."}, status=http.HTTP_400_BAD_REQUEST)
    return Response(ReturnDetailSerializer(ret).data)


# ======================================================= dispatches
@api_view(["GET"])
def dispatches(request):
    qs = Dispatch.objects.prefetch_related("orders").all()
    st = request.GET.get("status", "")
    if st:
        qs = qs.filter(status=st)
    return Response(DispatchSerializer(qs[:200], many=True).data)


@api_view(["GET"])
def dispatch_detail(request, pk):
    return Response(DispatchSerializer(get_object_or_404(Dispatch, pk=pk)).data)


# ======================================================= deliveries
@api_view(["GET"])
def deliveries(request):
    qs = DeliveryConfirmation.objects.select_related("order").all()
    return Response(DeliverySerializer(qs[:200], many=True, context={"request": request}).data)


@api_view(["GET"])
def delivery_detail(request, pk):
    obj = get_object_or_404(DeliveryConfirmation, pk=pk)
    return Response(DeliverySerializer(obj, context={"request": request}).data)


# ======================================================= accounting
def _acc_guard(request):
    """Accounting is admin-only."""
    return request.user.is_admin_role


@api_view(["GET"])
def accounting_summary(request):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    # Cash = sum of bank account balances
    cash = Z
    for a in Account.objects.filter(is_bank=True, is_active=True):
        try:
            cash += a.balance() + a.opening_balance
        except Exception:
            pass
    # A/R and A/P from open documents (truthful — every real invoice/bill counts)
    ar = sum((i.balance for i in Invoice.objects.exclude(
        status__in=[DocStatus.DRAFT, DocStatus.VOID]) if i.balance > 0), Z)
    ap = sum((b.balance for b in Bill.objects.exclude(
        status__in=[DocStatus.DRAFT, DocStatus.VOID]) if b.balance > 0), Z)
    overdue_ar = sum((i.balance for i in Invoice.objects.exclude(
        status__in=[DocStatus.DRAFT, DocStatus.VOID]) if i.balance > 0 and i.is_overdue), Z)
    # Income / expense (period = current year to date)
    start = timezone.localdate().replace(month=1, day=1)
    income = expense = Z
    for a in Account.objects.filter(type=AccountType.INCOME, is_active=True):
        try:
            income += a.balance(start=start)
        except Exception:
            pass
    for a in Account.objects.filter(type=AccountType.EXPENSE, is_active=True):
        try:
            expense += a.balance(start=start)
        except Exception:
            pass
    return Response({
        "cash": float(cash), "accounts_receivable": float(ar),
        "accounts_payable": float(ap), "overdue_receivable": float(overdue_ar),
        "income_ytd": float(abs(income)), "expense_ytd": float(abs(expense)),
        "net_income_ytd": float(abs(income) - abs(expense)),
        "open_invoices": Invoice.objects.exclude(
            status__in=[DocStatus.DRAFT, DocStatus.VOID]).count(),
        "open_bills": Bill.objects.exclude(
            status__in=[DocStatus.DRAFT, DocStatus.VOID]).count(),
    })


@api_view(["GET"])
def invoices(request):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    qs = Invoice.objects.select_related("customer").all()
    st = request.GET.get("status", "")
    if st == "open":
        qs = qs.exclude(status__in=[DocStatus.DRAFT, DocStatus.VOID])
    elif st:
        qs = qs.filter(status=st)
    return Response(InvoiceListSerializer(qs[:200], many=True).data)


@api_view(["GET"])
def invoice_detail(request, pk):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    return Response(InvoiceDetailSerializer(get_object_or_404(Invoice, pk=pk)).data)


@api_view(["GET"])
def bills(request):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    qs = Bill.objects.select_related("supplier").all()
    st = request.GET.get("status", "")
    if st == "open":
        qs = qs.exclude(status__in=[DocStatus.DRAFT, DocStatus.VOID])
    elif st:
        qs = qs.filter(status=st)
    return Response(BillListSerializer(qs[:200], many=True).data)


@api_view(["GET"])
def bill_detail(request, pk):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    return Response(BillDetailSerializer(get_object_or_404(Bill, pk=pk)).data)


@api_view(["GET"])
def payments(request):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    qs = Payment.objects.select_related("customer").all()
    return Response(PaymentSerializer(qs[:200], many=True).data)


@api_view(["GET"])
def chart_of_accounts(request):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    qs = Account.objects.filter(is_active=True).order_by("code")
    return Response(AccountSerializer(qs, many=True).data)


@api_view(["GET"])
def profit_loss(request):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    start = request.GET.get("start") or timezone.localdate().replace(month=1, day=1).isoformat()
    end = request.GET.get("end") or timezone.localdate().isoformat()
    income_rows, expense_rows = [], []
    income_total = expense_total = Z
    for a in Account.objects.filter(type=AccountType.INCOME, is_active=True).order_by("code"):
        bal = abs(a.balance(start=start, end=end))
        if bal:
            income_rows.append({"code": a.code, "name": a.name, "amount": float(bal)})
            income_total += bal
    for a in Account.objects.filter(type=AccountType.EXPENSE, is_active=True).order_by("code"):
        bal = abs(a.balance(start=start, end=end))
        if bal:
            expense_rows.append({"code": a.code, "name": a.name, "amount": float(bal)})
            expense_total += bal
    return Response({
        "start": start, "end": end,
        "income": income_rows, "income_total": float(income_total),
        "expense": expense_rows, "expense_total": float(expense_total),
        "net_income": float(income_total - expense_total),
    })


@api_view(["GET"])
def balance_sheet(request):
    if not _acc_guard(request):
        return Response({"detail": "Admins only."}, status=http.HTTP_403_FORBIDDEN)
    groups = {"asset": [], "liability": [], "equity": []}
    totals = {"asset": Z, "liability": Z, "equity": Z}
    typemap = {AccountType.ASSET: "asset", AccountType.LIABILITY: "liability",
               AccountType.EQUITY: "equity"}
    for a in Account.objects.filter(is_active=True).order_by("code"):
        key = typemap.get(a.type)
        if not key:
            continue
        try:
            bal = a.balance() + a.opening_balance
        except Exception:
            bal = Z
        if bal:
            groups[key].append({"code": a.code, "name": a.name, "amount": float(abs(bal))})
            totals[key] += abs(bal)
    return Response({
        "assets": groups["asset"], "assets_total": float(totals["asset"]),
        "liabilities": groups["liability"], "liabilities_total": float(totals["liability"]),
        "equity": groups["equity"], "equity_total": float(totals["equity"]),
    })
