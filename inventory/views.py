from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import Role
from catalogue.models import Product, StockMovement, Category
from core.permissions import role_required
from .forms import SupplierForm, PurchaseOrderForm
from .models import Supplier, PurchaseOrder, PurchaseOrderLine

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
            po.save()
            any_line = False
            for p in products:
                qty = _dec(request.POST.get(f"qty_{p.id}"))
                cost = _dec(request.POST.get(f"cost_{p.id}"), str(p.cost_price))
                if qty > 0:
                    PurchaseOrderLine.objects.create(
                        po=po, product=p, qty_ordered=qty, unit_cost=cost)
                    any_line = True
            if not any_line:
                po.delete()
                messages.error(request, "Add a quantity for at least one product.")
                return redirect("po_create")
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
