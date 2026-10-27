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


def _rebuild_po_lines(request, po, products, rate, mark_received=False):
    """Shared by create + edit. Reads the posted qty/usd/cost/sell + expenses,
    works out the landed multiplier and (re)writes the PO's lines & expenses.
    Returns an error string, or None on success."""
    # ---- Pass 1: gather the lines (USD price) + expenses.
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
        return "Add a quantity for at least one product."

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

    goods_bzd = goods_usd * rate
    ratio = ((goods_bzd + expenses_bzd) / goods_bzd) if goods_bzd > 0 else Decimal("1")
    landed_mult = rate * ratio

    # ---- Replace the PO's lines & expenses (edit re-saves from scratch).
    po.lines.all().delete()
    po.expenses.all().delete()
    for p, qty, usd, cost_override, sell in pending:
        landed = cost_override if cost_override is not None else (usd * landed_mult)
        # Keep 6 decimals so qty × unit_cost sums to the exact landed total.
        PurchaseOrderLine.objects.create(
            po=po, product=p, qty_ordered=qty, unit_cost_usd=usd,
            unit_cost=Decimal(landed).quantize(Decimal("0.000001")), sell_price=sell,
            qty_received=(qty if mark_received else Decimal("0")),
        )
    for nm, amt, cur in exp_rows:
        PurchaseOrderExpense.objects.create(po=po, name=nm, amount=amt, currency=cur)
    return None


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
            po.exchange_rate = rate if rate > 0 else Decimal("1")
            po.save()
            err = _rebuild_po_lines(request, po, products, po.exchange_rate)
            if err:
                po.delete()
                messages.error(request, err)
                return redirect("po_create")
            messages.success(request, f"{po.po_no} created.")
            if request.POST.get("save_close"):
                return redirect("po_list")
            return redirect("po_detail", pk=po.pk)
    else:
        form = PurchaseOrderForm()
    categories = Category.objects.all().order_by("name")
    return render(request, "inventory/po_form.html",
                  {"form": form, "products": products, "categories": categories})


def _po_dependencies(po):
    """What a received PO is tied to downstream — used to warn before an edit or
    delete. Returns a dict the templates render."""
    bills, bill_total, paid_total = [], Decimal("0.00"), Decimal("0.00")
    try:
        for b in po.bills.all():
            tot = b.total
            paid = b.amount_paid
            bill_total += tot
            paid_total += paid
            bills.append({"number": b.number, "total": tot, "paid": paid,
                          "status": b.get_status_display()})
    except Exception:
        pass
    received_lines = []
    if po.status == PurchaseOrder.Status.RECEIVED:
        for l in po.lines.select_related("product").all():
            qty = l.qty_received or l.qty_ordered
            if l.product and l.product.track_stock and qty:
                received_lines.append((l.product, qty))
    return {
        "received": po.status == PurchaseOrder.Status.RECEIVED,
        "bills": bills, "bill_total": bill_total, "paid_total": paid_total,
        "has_paid_bill": paid_total > 0,
        "received_lines": received_lines,
        "price_updated": po.status == PurchaseOrder.Status.RECEIVED,
    }


@role_required(*INV_ROLES)
def po_edit(request, pk):
    """Edit a purchase order at any status — quantities, prices, expenses, FX,
    supplier. For a received PO the dependency warning is shown; the edit updates
    the PO document only and does not silently re-post stock or the supplier bill."""
    po = get_object_or_404(PurchaseOrder, pk=pk)
    products = Product.objects.filter(is_active=True).select_related("category")
    if request.method == "POST":
        form = PurchaseOrderForm(request.POST, instance=po)
        if form.is_valid():
            po = form.save(commit=False)
            rate = _dec(request.POST.get("exchange_rate"), "2.00")
            po.exchange_rate = rate if rate > 0 else Decimal("1")
            po.save()
            was_received = po.status == PurchaseOrder.Status.RECEIVED
            err = _rebuild_po_lines(request, po, products, po.exchange_rate,
                                    mark_received=was_received)
            if err:
                messages.error(request, err)
                return redirect("po_edit", pk=po.pk)
            if was_received:
                messages.warning(request, f"{po.po_no} updated. Note: stock already "
                                 "received and the posted supplier bill were NOT changed "
                                 "— adjust them in Inventory / Accounting if needed.")
            else:
                messages.success(request, f"{po.po_no} updated.")
            if request.POST.get("save_close"):
                return redirect("po_list")
            return redirect("po_detail", pk=po.pk)
    else:
        form = PurchaseOrderForm(instance=po)

    # Annotate each product with its existing line values so the form prefills.
    line_map = {l.product_id: l for l in po.lines.all()}
    for p in products:
        l = line_map.get(p.id)
        p.po_qty = f"{l.qty_ordered:g}" if l else ""
        p.po_usd = f"{l.unit_cost_usd:g}" if (l and l.unit_cost_usd) else ""
        p.po_cost = f"{l.unit_cost:g}" if (l and l.unit_cost) else ""
        p.po_sell = f"{l.sell_price:g}" if (l and l.sell_price) else ""
    existing_expenses = [
        {"name": e.name, "amount": f"{e.amount:g}", "currency": e.currency}
        for e in po.expenses.all()
    ]
    categories = Category.objects.all().order_by("name")
    return render(request, "inventory/po_form.html", {
        "form": form, "products": products, "categories": categories,
        "po": po, "editing": True, "existing_expenses": existing_expenses,
        "deps": _po_dependencies(po),
    })


@role_required(*INV_ROLES)
def po_delete(request, pk):
    """Delete a PO at any status. A draft deletes cleanly. A received PO also
    reverses its received stock and voids/removes the (unpaid) supplier bill so
    accounts stay consistent; a PAID bill blocks the delete until it's unpaid."""
    po = get_object_or_404(PurchaseOrder, pk=pk)
    deps = _po_dependencies(po)
    if request.method != "POST":
        return render(request, "inventory/po_confirm_delete.html", {"po": po, "deps": deps})

    if deps["has_paid_bill"]:
        messages.error(request, f"{po.po_no} can't be deleted — a payment is recorded "
                        "against its supplier bill. Reverse the payment in Accounting first.")
        return redirect("po_detail", pk=pk)

    po_no = po.po_no
    # Reverse received stock (goods are no longer considered received).
    if deps["received"]:
        from catalogue.models import StockMovement
        for product, qty in deps["received_lines"]:
            try:
                product.adjust_stock(-qty, StockMovement.Kind.ADJUST, user=request.user,
                                     note=f"{po_no} deleted — reverse goods receipt")
            except Exception:
                pass
    # Void + remove the (unpaid) supplier bill so A/P isn't left dangling.
    try:
        from accounting.services import _void_entry
        for b in list(po.bills.all()):
            if b.journal_id:
                _void_entry(b.journal)
            b.delete()
    except Exception:
        pass

    po.delete()  # cascades lines + expenses
    messages.success(request, f"{po_no} deleted."
                     + (" Received stock reversed and its supplier bill voided."
                        if deps["received"] else ""))
    return redirect("po_list")


@role_required(*INV_ROLES)
def po_quick_product(request):
    """Create a product inline from the New-PO screen and return it as JSON so
    the row can be added to the order straight away. Also stored in the catalogue."""
    from django.http import JsonResponse
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)

    name = (request.POST.get("name") or "").strip()
    sku = (request.POST.get("sku") or "").strip()
    category_id = request.POST.get("category")
    unit = (request.POST.get("unit") or "pcs").strip()
    if not name or not sku or not category_id:
        return JsonResponse({"ok": False, "error": "Name, SKU and category are required."}, status=400)
    if Product.objects.filter(sku__iexact=sku).exists():
        return JsonResponse({"ok": False, "error": f"SKU '{sku}' already exists."}, status=400)
    category = Category.objects.filter(pk=category_id).first()
    if not category:
        return JsonResponse({"ok": False, "error": "Pick a valid category."}, status=400)
    valid_units = {c[0] for c in Product.Unit.choices}
    if unit not in valid_units:
        unit = Product.Unit.PIECE

    p = Product.objects.create(
        name=name, sku=sku, category=category, unit=unit,
        selling_price=_dec(request.POST.get("selling_price")),
        cost_price=_dec(request.POST.get("cost_price")),
        track_stock=(request.POST.get("track_stock") == "on"),
        taxable=(request.POST.get("taxable", "on") != "off"),
        is_active=True,
    )
    return JsonResponse({
        "ok": True, "id": p.id, "name": p.name, "sku": p.sku,
        "category_id": p.category_id, "unit_label": p.get_unit_display(),
        "track_stock": p.track_stock, "stock_qty": f"{p.stock_qty:g}",
    })


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
    # Simplified flow: a PO is Draft until it is Received (no Ordered / Cancelled).
    if action == "receive" and po.status != PurchaseOrder.Status.RECEIVED:
        received_map = {}
        for line in po.lines.all():
            received_map[str(line.id)] = _dec(
                request.POST.get(f"recv_{line.id}"), str(line.qty_ordered))
        po.receive(user=request.user, received_map=received_map)
        messages.success(request, f"{po.po_no} received — stock updated.")
    return redirect("po_detail", pk=pk)