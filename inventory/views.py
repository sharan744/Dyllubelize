from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import Role
from catalogue.models import Product, StockMovement, Category
from core.permissions import role_required
from .forms import SupplierForm, PurchaseOrderForm
from .models import Supplier, PurchaseOrder, PurchaseOrderLine, PurchaseOrderExpense

INV_ROLES = (Role.PROCESSING, Role.DISPATCH)


def _dec(v, default="0"):
    try:
        return Decimal(str(v if v not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


# ============================================================
# Inventory overview + quick stock-in
# ============================================================
@role_required(*INV_ROLES)
def inventory_overview(request):
    q = request.GET.get("q", "").strip()
    only_low = request.GET.get("low") == "1"
    products = Product.objects.filter(track_stock=True).select_related("category")
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    products = list(products)
    if only_low:
        products = [p for p in products if p.needs_reorder]

    total_value = sum((p.stock_value for p in products), Decimal("0.00"))
    low_count = sum(1 for p in products if p.needs_reorder)
    return render(request, "inventory/overview.html", {
        "products": products, "q": q, "only_low": only_low,
        "total_value": total_value, "low_count": low_count,
    })


@role_required(*INV_ROLES)
def stock_adjust(request):
    import datetime
    if request.method == "POST":
        product = get_object_or_404(Product, pk=request.POST.get("product"))
        qty = _dec(request.POST.get("qty"))
        note = request.POST.get("note", "").strip()
        action = request.POST.get("action", "add")
        # optional expiry date for a perishable batch being received
        expiry = None
        raw_exp = request.POST.get("expiry", "").strip()
        if raw_exp:
            try:
                expiry = datetime.date.fromisoformat(raw_exp)
            except ValueError:
                expiry = None
        if qty <= 0:
            messages.error(request, "Enter a quantity greater than zero.")
        elif action == "add":
            product.adjust_stock(qty, StockMovement.Kind.RESTOCK,
                                 user=request.user, note=note or "Manual stock-in",
                                 expiry=expiry)
            extra = f" (expires {expiry})" if expiry else ""
            messages.success(request, f"Added {qty:g} to {product.name}{extra}. New stock: {product.stock_qty:g}.")
        elif action == "remove":
            product.adjust_stock(-qty, StockMovement.Kind.ADJUST,
                                 user=request.user, note=note or "Manual removal")
            messages.info(request, f"Removed {qty:g} from {product.name}. New stock: {product.stock_qty:g}.")
    return redirect(request.POST.get("next") or "inventory_overview")


@role_required(*INV_ROLES)
def expiring_soon(request):
    """Perishable batches that are expired or within their alert window."""
    import datetime
    from catalogue.models import StockBatch
    today = datetime.date.today()
    horizon = int(request.GET.get("days", 14) or 14)
    limit = today + datetime.timedelta(days=horizon)
    batches = (StockBatch.objects.filter(qty_remaining__gt=0)
               .exclude(expiry_date=None)
               .filter(expiry_date__lte=limit)
               .select_related("product", "supplier")
               .order_by("expiry_date", "received_date"))
    expired = [b for b in batches if b.is_expired]
    soon = [b for b in batches if not b.is_expired]
    return render(request, "inventory/expiring.html", {
        "expired": expired, "soon": soon, "horizon": horizon, "today": today,
    })


# ============================================================
# Suppliers
# ============================================================
@role_required(*INV_ROLES)
def supplier_list(request):
    suppliers = Supplier.objects.all()
    return render(request, "inventory/supplier_list.html", {"suppliers": suppliers})


@role_required(*INV_ROLES)
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier added.")
        return redirect("supplier_list")
    return render(request, "inventory/supplier_form.html", {"form": form, "title": "Add Supplier"})


@role_required(*INV_ROLES)
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier updated.")
        return redirect("supplier_list")
    return render(request, "inventory/supplier_form.html",
                  {"form": form, "title": f"Edit {supplier.name}"})


# ============================================================
# Purchase Orders
# ============================================================
@role_required(*INV_ROLES)
def po_list(request):
    pos = PurchaseOrder.objects.select_related("supplier").prefetch_related("lines")
    return render(request, "inventory/po_list.html", {"pos": pos})


@role_required(*INV_ROLES)
def po_create(request):
    products = Product.objects.filter(is_active=True).select_related("category")
    if request.method == "POST":
        form = PurchaseOrderForm(request.POST)
        if form.is_valid():
            po = form.save(commit=False)
            po.created_by = request.user
            po.status = PurchaseOrder.Status.DRAFT
            rate = _dec(request.POST.get("exchange_rate"), "2.00")
            if rate <= 0:
                rate = Decimal("1")
            po.exchange_rate = rate
            po.save()

            # ---- Pass 1: gather the lines (USD price) and expenses, so we can
            # work out the landed multiplier (FX × expense ratio) for the whole PO.
            pending = []  # (product, qty, usd_price, cost_override_or_None, sell)
            goods_usd = Decimal("0.00")
            for p in products:
                qty = _dec(request.POST.get(f"qty_{p.id}"))
                if qty <= 0:
                    continue
                usd = _dec(request.POST.get(f"usd_{p.id}"))
                raw_cost = (request.POST.get(f"cost_{p.id}") or "").strip()
                cost_override = _dec(raw_cost) if raw_cost else None
                sell = _dec(request.POST.get(f"sell_{p.id}"))
                pending.append((p, qty, usd, cost_override, sell))
                goods_usd += qty * usd

            if not pending:
                po.delete()
                messages.error(request, "Add a quantity for at least one product.")
                return redirect("po_create")

            # Expenses (name, amount, currency) — USD expenses convert to BZD.
            exp_names = request.POST.getlist("expense_name")
            exp_amounts = request.POST.getlist("expense_amount")
            exp_currencies = request.POST.getlist("expense_currency")
            expenses_bzd = Decimal("0.00")
            exp_rows = []
            for i, nm in enumerate(exp_names):
                nm = (nm or "").strip()
                amt = _dec(exp_amounts[i] if i < len(exp_amounts) else "0")
                cur = (exp_currencies[i] if i < len(exp_currencies) else "BZD").upper()
                if cur not in ("BZD", "USD"):
                    cur = "BZD"
                if nm and amt > 0:
                    exp_rows.append((nm, amt, cur))
                    expenses_bzd += amt * rate if cur == "USD" else amt

            # Landed multiplier: USD → BZD landed cost, expenses spread by value.
            goods_bzd = goods_usd * rate
            ratio = ((goods_bzd + expenses_bzd) / goods_bzd) if goods_bzd > 0 else Decimal("1")
            landed_mult = rate * ratio

            # ---- Pass 2: write the lines with their landed cost.
            for p, qty, usd, cost_override, sell in pending:
                landed = cost_override if cost_override is not None else (usd * landed_mult)
                PurchaseOrderLine.objects.create(
                    po=po, product=p, qty_ordered=qty,
                    unit_cost_usd=usd,
                    unit_cost=Decimal(landed).quantize(Decimal("0.01")),
                    sell_price=sell,
                )
            for nm, amt, cur in exp_rows:
                PurchaseOrderExpense.objects.create(po=po, name=nm, amount=amt, currency=cur)

            messages.success(request, f"{po.po_no} created.")
            return redirect("po_detail", pk=po.pk)
    else:
        form = PurchaseOrderForm()
    return render(request, "inventory/po_form.html", {"form": form, "products": products})


@role_required(*INV_ROLES)
def po_detail(request, pk):
    po = get_object_or_404(
        PurchaseOrder.objects.select_related("supplier").prefetch_related("lines__product"), pk=pk)
    return render(request, "inventory/po_detail.html", {"po": po})


@role_required(*INV_ROLES)
def po_action(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    if request.method != "POST":
        return redirect("po_detail", pk=pk)
    action = request.POST.get("action")
    if action == "order" and po.status == PurchaseOrder.Status.DRAFT:
        po.status = PurchaseOrder.Status.ORDERED
        po.save(update_fields=["status"])
        messages.info(request, f"{po.po_no} marked as ordered.")
    elif action == "receive" and po.status != PurchaseOrder.Status.RECEIVED:
        received_map = {}
        for line in po.lines.all():
            received_map[str(line.id)] = _dec(
                request.POST.get(f"recv_{line.id}"), str(line.qty_ordered))
        po.receive(user=request.user, received_map=received_map)
        messages.success(request, f"{po.po_no} received — stock updated.")
    elif action == "cancel" and po.status != PurchaseOrder.Status.RECEIVED:
        po.status = PurchaseOrder.Status.CANCELLED
        po.save(update_fields=["status"])
        messages.warning(request, f"{po.po_no} cancelled.")
    return redirect("po_detail", pk=pk)