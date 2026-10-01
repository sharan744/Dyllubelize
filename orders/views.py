import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.models import Role
from catalogue.models import Product
from core.permissions import role_required, ALL_STAFF
from .forms import CustomerForm
from .models import Customer, Order, OrderItem, OrderStatus


# ============================================================
# Customers
# ============================================================
@role_required(Role.SALES, Role.TEAM_LEAD)
def customer_list(request):
    q = request.GET.get("q", "").strip()
    customers = Customer.objects.all()
    if q:
        customers = customers.filter(
            Q(name__icontains=q) | Q(company_name__icontains=q) | Q(mobile__icontains=q)
        )
    return render(request, "orders/customer_list.html", {"customers": customers, "q": q})


@role_required(Role.SALES, Role.TEAM_LEAD)
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return render(request, "orders/customer_detail.html", {
        "customer": customer,
        "orders": customer.orders.all()[:20],
    })


@role_required(Role.SALES, Role.TEAM_LEAD)
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        customer.created_by = request.user
        customer.save()
        messages.success(request, "Customer added.")
        nxt = request.GET.get("next")
        if nxt == "order":
            return redirect(f"{request.build_absolute_uri('/orders/new/')}?customer={customer.pk}")
        return redirect("customer_detail", pk=customer.pk)
    return render(request, "orders/customer_form.html", {"form": form, "title": "Add Customer"})


@role_required(Role.SALES, Role.TEAM_LEAD)
def customer_search_api(request):
    q = request.GET.get("q", "").strip()
    cid = request.GET.get("id")
    customers = Customer.objects.all()
    if cid:
        customers = customers.filter(pk=cid)
    elif q:
        customers = customers.filter(
            Q(name__icontains=q) | Q(company_name__icontains=q) | Q(mobile__icontains=q)
        )
    data = [{
        "id": c.pk, "name": c.name, "company": c.company_name,
        "mobile": c.mobile, "email": c.email,
        "delivery_address": c.delivery_address, "orders": c.order_count,
    } for c in customers[:15]]
    return JsonResponse({"results": data})


# ============================================================
# Order creation (Sales)
# ============================================================
def _active_products_json():
    products = (Product.objects.filter(is_active=True)
                .select_related("category").prefetch_related("price_breaks"))
    return json.dumps([{
        "id": p.pk, "name": p.name, "sku": p.sku,
        "unit": p.get_unit_display(), "price": float(p.selling_price),
        "category": p.category.name, "category_id": p.category_id,
        "brand": p.brand or "",
        "desc": p.long_description or "",
        "image": p.image.url if p.image else "",
        "stock": float(p.stock_qty), "track": p.track_stock,
        "breaks": [[float(b.min_qty), float(b.price)]
                   for b in p.price_breaks.all()],
    } for p in products])


@role_required(*ALL_STAFF)
def product_info_api(request, pk):
    """Product description + specs + similar products, for the order-builder modal."""
    from catalogue.models import Product
    p = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("specs"), pk=pk)
    similar = []
    for sp in p.similar_products(limit=6):
        similar.append({
            "id": sp.pk, "name": sp.name, "sku": sp.sku,
            "price": float(sp.selling_price),
            "image": sp.image.url if sp.image else "",
        })
    return JsonResponse({
        "id": p.pk, "name": p.name, "sku": p.sku, "brand": p.brand,
        "unit": p.get_unit_display(), "price": float(p.selling_price),
        "category": p.category.name if p.category else "",
        "image": p.image.url if p.image else "",
        "description": p.long_description or "",
        "specs": [{"label": s.label, "value": s.value} for s in p.specs.all()],
        "similar": similar,
    })


@role_required(Role.SALES)
def pricing_api(request):
    """Customer-specific price overrides for the order builder."""
    from catalogue.models import CustomerPrice
    cid = request.GET.get("customer")
    data = {}
    if cid:
        for cp in CustomerPrice.objects.filter(customer_id=cid):
            data[str(cp.product_id)] = float(cp.price)
    return JsonResponse({"prices": data})


@role_required(Role.SALES)
def order_create(request):
    if request.method == "POST":
        return _save_order(request, order=None)

    preset_customer = request.GET.get("customer")
    return render(request, "orders/order_form.html", {
        "products_json": _active_products_json(),
        "customer_form": CustomerForm(),
        "preset_customer_id": preset_customer or "",
        "order": None,
        "items_json": "[]",
    })


@role_required(Role.SALES)
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.salesperson_id != request.user.id and not request.user.is_admin_role:
        raise PermissionDenied
    if order.status not in (OrderStatus.DRAFT, OrderStatus.REJECTED):
        messages.warning(request, "This order can no longer be edited.")
        return redirect("order_detail", pk=order.pk)

    if request.method == "POST":
        return _save_order(request, order=order)

    items = [{
        "id": i.product_id, "name": i.product_name, "sku": i.sku,
        "unit": i.unit, "price": float(i.unit_price),
        "qty": float(i.quantity), "discount": float(i.line_discount_percent),
        "note": i.note,
    } for i in order.items.all()]
    return render(request, "orders/order_form.html", {
        "products_json": _active_products_json(),
        "customer_form": CustomerForm(),
        "preset_customer_id": order.customer_id,
        "order": order,
        "items_json": json.dumps(items),
    })


def _save_order(request, order=None):
    customer_id = request.POST.get("customer_id")
    if not customer_id:
        messages.error(request, "Please select or create a customer first.")
        return redirect("order_create")
    customer = get_object_or_404(Customer, pk=customer_id)

    try:
        items = json.loads(request.POST.get("items_json", "[]"))
    except json.JSONDecodeError:
        items = []
    if not items:
        messages.error(request, "Add at least one product to the order.")
        return redirect("order_create")

    remarks = request.POST.get("remarks", "").strip()
    try:
        discount = Decimal(request.POST.get("discount_percent") or "0")
    except InvalidOperation:
        discount = Decimal("0")
    action = request.POST.get("action", "draft")

    if order is None:
        order = Order(customer=customer, salesperson=request.user)
    order.customer = customer
    order.remarks = remarks
    order.discount_percent = discount
    order.save()

    # rebuild items
    order.items.all().delete()
    for it in items:
        try:
            product = Product.objects.get(pk=it["id"])
        except (Product.DoesNotExist, KeyError):
            continue
        OrderItem.objects.create(
            order=order, product=product,
            product_name=product.name, sku=product.sku, unit=product.get_unit_display(),
            unit_price=Decimal(str(it.get("price", product.selling_price))),
            quantity=Decimal(str(it.get("qty", 1) or 1)),
            line_discount_percent=Decimal(str(it.get("discount", 0) or 0)),
            note=str(it.get("note", ""))[:255],
        )

    if action == "submit":
        order.set_status(OrderStatus.SUBMITTED, user=request.user, note="Submitted by salesperson")
        from core.notifications import notify_new_order
        notify_new_order(order)
        messages.success(request, f"Order {order.order_no} submitted for Team Lead review.")
    else:
        if order.status != OrderStatus.DRAFT:
            order.status = OrderStatus.DRAFT
            order.save()
        messages.success(request, f"Order {order.order_no} saved as draft.")
    return redirect("order_detail", pk=order.pk)


# ============================================================
# Order detail & tracking
# ============================================================
@role_required(*ALL_STAFF)
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("customer", "salesperson"), pk=pk
    )
    from orders.models import STATUS_PIPELINE
    pipeline = [{"key": s.value, "label": s.label} for s in STATUS_PIPELINE]
    return render(request, "orders/order_detail.html", {
        "order": order,
        "pipeline": pipeline,
        "logs": order.status_logs.select_related("changed_by"),
        "delivery": getattr(order, "delivery", None),
    })


@role_required(Role.TEAM_LEAD)
def order_cancel(request, pk):
    """Cancel an order and return its quantities to stock (admin / team lead)."""
    order = get_object_or_404(Order, pk=pk)
    if request.method == "POST":
        if order.status == OrderStatus.CANCELLED:
            messages.info(request, "Order is already cancelled.")
        else:
            note = request.POST.get("note", "").strip()
            order.set_status(OrderStatus.CANCELLED, user=request.user,
                             note=note or "Cancelled / returned to warehouse")
            if order.stock_committed is False:
                messages.warning(request, f"Order {order.order_no} cancelled. "
                                          f"Stock returned to the warehouse.")
            else:
                messages.warning(request, f"Order {order.order_no} cancelled.")
    return redirect("order_detail", pk=pk)


@role_required(*ALL_STAFF)
def order_quotation(request, pk):
    """Printable, priced quotation for the customer (with configurable tax)."""
    from datetime import timedelta
    from decimal import Decimal
    from core.models import SiteSetting

    order = get_object_or_404(
        Order.objects.select_related("customer", "salesperson"), pk=pk
    )
    site = SiteSetting.get()

    net = order.total  # subtotal minus order discount
    if site.tax_enabled and site.tax_percent:
        tax_amount = (net * site.tax_percent / Decimal("100")).quantize(Decimal("0.01"))
    else:
        tax_amount = Decimal("0.00")
    grand_total = net + tax_amount
    valid_until = timezone.localdate() + timedelta(days=site.quote_validity_days or 15)

    return render(request, "orders/quotation.html", {
        "order": order,
        "net": net,
        "tax_amount": tax_amount,
        "grand_total": grand_total,
        "valid_until": valid_until,
    })


@role_required(*ALL_STAFF)
def order_list(request):
    orders = Order.objects.select_related("customer", "salesperson").all()

    # Sales people see only their own orders
    if request.user.is_sales:
        orders = orders.filter(salesperson=request.user)

    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    sp = request.GET.get("salesperson", "")
    date = request.GET.get("date", "")

    if status:
        orders = orders.filter(status=status)
    if q:
        orders = orders.filter(
            Q(order_no__icontains=q) | Q(customer__name__icontains=q)
            | Q(customer__company_name__icontains=q)
        )
    if sp:
        orders = orders.filter(salesperson_id=sp)
    if date:
        orders = orders.filter(created_at__date=date)

    from accounts.models import User
    from django.core.paginator import Paginator
    salespeople = User.objects.filter(role=Role.SALES)

    paginator = Paginator(orders.order_by("-created_at"), 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    # querystring for pager links, without the page param
    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()

    return render(request, "orders/order_list.html", {
        "orders": page_obj,
        "page_obj": page_obj,
        "querystring": querystring,
        "statuses": OrderStatus.choices,
        "salespeople": salespeople,
        "f": {"status": status, "q": q, "salesperson": sp, "date": date},
    })


# ============================================================
# Team Lead review
# ============================================================
@role_required(Role.TEAM_LEAD)
def review_queue(request):
    orders = Order.objects.filter(
        status__in=[OrderStatus.SUBMITTED, OrderStatus.TEAM_LEAD_REVIEW]
    ).select_related("customer", "salesperson")
    return render(request, "orders/review_queue.html", {"orders": orders})


@role_required(Role.TEAM_LEAD)
def order_review_action(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)

    action = request.POST.get("action")
    note = request.POST.get("note", "").strip()
    if note:
        order.team_lead_remarks = note
        order.save(update_fields=["team_lead_remarks"])

    if action == "confirm":
        order.set_status(OrderStatus.CONFIRMED, user=request.user,
                         note=note or "Confirmed by Team Lead")
        messages.success(request, f"Order {order.order_no} confirmed.")
    elif action == "reject":
        order.set_status(OrderStatus.REJECTED, user=request.user,
                         note=note or "Returned for correction")
        messages.warning(request, f"Order {order.order_no} returned to salesperson.")
    return redirect("review_queue")


# ============================================================
# Processing team
# ============================================================
@role_required(Role.PROCESSING)
def processing_queue(request):
    orders = Order.objects.filter(
        status__in=[OrderStatus.CONFIRMED, OrderStatus.PROCESSING]
    ).select_related("customer")
    return render(request, "orders/processing_queue.html", {"orders": orders})


@role_required(Role.PROCESSING)
def processing_action(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method != "POST":
        return redirect("order_detail", pk=pk)
    action = request.POST.get("action")
    if action == "start" and order.status == OrderStatus.CONFIRMED:
        order.set_status(OrderStatus.PROCESSING, user=request.user, note="Processing started")
        messages.info(request, f"Order {order.order_no} moved to Processing.")
    elif action == "ready":
        order.set_status(OrderStatus.READY, user=request.user, note="Ready for dispatch")
        messages.success(request, f"Order {order.order_no} is Ready for Dispatch.")
    return redirect("processing_queue")