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
        "orders": customer.orders.select_related("invoice").all()[:20],
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

    # Inline price/qty editing is allowed for the owning salesperson or an admin,
    # and only while the order is still open (not completed/rejected/cancelled).
    can_edit = order.is_open and (
        request.user.is_admin_role or order.salesperson_id == request.user.id)

    return render(request, "orders/quotation.html", {
        "order": order,
        "net": net,
        "tax_amount": tax_amount,
        "grand_total": grand_total,
        "valid_until": valid_until,
        "can_edit": can_edit,
    })


# ============================================================
# Order invoice — printable view + PDF download
# ============================================================
def _invoice_context(order):
    """Build the figures + meta for an order's invoice. If a formal accounting
    Invoice exists for the order, its number / date / due / paid / balance are
    used; otherwise the invoice is drawn straight from the order."""
    from decimal import Decimal
    from core.models import SiteSetting
    site = SiteSetting.get()

    net = order.total  # subtotal minus order discount
    if site.tax_enabled and site.tax_percent:
        tax_amount = (net * site.tax_percent / Decimal("100")).quantize(Decimal("0.01"))
    else:
        tax_amount = Decimal("0.00")
    grand_total = net + tax_amount

    inv = getattr(order, "invoice", None)
    if inv is not None:
        number = inv.number
        inv_date = inv.date
        due_date = inv.due_date
        amount_paid = inv.amount_paid
        balance = (grand_total - amount_paid)
        status = inv.get_status_display()
        status_code = inv.status
    else:
        number = order.order_no
        inv_date = (order.completed_at or order.confirmed_at or order.created_at)
        try:
            inv_date = timezone.localtime(inv_date).date()
        except Exception:
            inv_date = timezone.localdate()
        due_date = inv_date + timezone.timedelta(days=30)
        amount_paid = Decimal("0.00")
        balance = grand_total
        status = "Proforma" if order.is_open else "Issued"
        status_code = "open"

    return {
        "order": order, "site": site,
        "net": net, "tax_amount": tax_amount, "grand_total": grand_total,
        "inv_number": number, "inv_date": inv_date, "due_date": due_date,
        "amount_paid": amount_paid, "balance": balance,
        "inv_status": status, "inv_status_code": status_code,
        "has_invoice": inv is not None,
    }


@role_required(*ALL_STAFF)
def order_invoice(request, pk):
    """Printable invoice for a single order (view + Save as PDF / Download PDF)."""
    order = get_object_or_404(
        Order.objects.select_related("customer", "salesperson").prefetch_related("items"),
        pk=pk,
    )
    return render(request, "orders/invoice.html", _invoice_context(order))


@role_required(*ALL_STAFF)
def order_invoice_pdf(request, pk):
    """Server-generated PDF of the order invoice (reportlab)."""
    from django.http import HttpResponse
    order = get_object_or_404(
        Order.objects.select_related("customer", "salesperson").prefetch_related("items"),
        pk=pk,
    )
    ctx = _invoice_context(order)
    pdf_bytes = _render_invoice_pdf(ctx)
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="Invoice-{ctx["inv_number"]}.pdf"'
    return resp


def _render_invoice_pdf(ctx):
    """Lay out the invoice with reportlab and return the PDF as bytes."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)

    order = ctx["order"]
    site = ctx["site"]
    sym = site.currency_symbol or "$"

    def money(v):
        return f"{sym}{v:,.2f}"

    DARK = colors.HexColor("#1b1a24")
    ACC = colors.HexColor("#e0603a")
    MUTE = colors.HexColor("#6b6577")
    LINE = colors.HexColor("#d9d2c4")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Invoice {ctx['inv_number']}")
    ss = getSampleStyleSheet()
    h_co = ParagraphStyle("co", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=17, textColor=DARK, leading=20)
    tag = ParagraphStyle("tag", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=7.5, textColor=ACC, leading=10)
    small = ParagraphStyle("small", parent=ss["Normal"], fontSize=8, textColor=MUTE, leading=12)
    lbl = ParagraphStyle("lbl", parent=ss["Normal"], fontName="Helvetica-Bold",
                         fontSize=7.5, textColor=ACC, leading=12)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=9, leading=13)
    bodyb = ParagraphStyle("bodyb", parent=ss["Normal"], fontName="Helvetica-Bold",
                           fontSize=9.5, leading=13, textColor=DARK)
    titleR = ParagraphStyle("titleR", parent=ss["Normal"], fontName="Helvetica-Bold",
                            fontSize=15, textColor=ACC, alignment=2, leading=18)
    dnoR = ParagraphStyle("dnoR", parent=ss["Normal"], fontName="Courier-Bold",
                          fontSize=13, textColor=DARK, alignment=2, leading=16)
    metaR = ParagraphStyle("metaR", parent=ss["Normal"], fontSize=8.5, textColor=MUTE,
                           alignment=2, leading=13)
    cellR = ParagraphStyle("cellR", parent=ss["Normal"], fontSize=9, alignment=2, leading=12)
    cellL = ParagraphStyle("cellL", parent=ss["Normal"], fontSize=9, leading=12)

    story = []

    # ---- Header: company (left) + invoice meta (right) ----
    co_lines = [Paragraph(site.tagline or "", tag), Paragraph(site.company_name or "", h_co)]
    info = []
    if site.address:
        info.append(site.address.replace("\n", "<br/>"))
    tp = []
    if site.phone:
        tp.append(f"Tel: {site.phone}")
    if site.email:
        tp.append(site.email)
    if tp:
        info.append(" · ".join(tp))
    if getattr(site, "tax_id", ""):
        info.append(f"Tax ID: {site.tax_id}")
    if info:
        co_lines.append(Paragraph("<br/>".join(info), small))
    co_cell = co_lines

    meta_tbl = Table([
        [Paragraph("INVOICE", titleR)],
        [Paragraph(ctx["inv_number"], dnoR)],
        [Paragraph(
            f"Date: <b>{ctx['inv_date']:%d %b %Y}</b><br/>"
            f"Due: <b>{ctx['due_date']:%d %b %Y}</b><br/>"
            f"Order: <b>{order.order_no}</b><br/>"
            f"Salesperson: <b>{(order.salesperson.display_name if order.salesperson else '-')}</b>",
            metaR)],
    ], colWidths=[70 * mm])
    meta_tbl.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))

    head = Table([[co_cell, meta_tbl]], colWidths=[98 * mm, 70 * mm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 2, DARK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [head, Spacer(1, 10)]

    # ---- Bill to / Billing address ----
    cust = order.customer
    billto = [Paragraph("BILL TO", lbl),
              Paragraph(cust.company_name or cust.name or "", bodyb)]
    line2 = []
    if cust.company_name and cust.name:
        line2.append(f"Attn: {cust.name}")
    if cust.mobile:
        line2.append(cust.mobile)
    if cust.email:
        line2.append(cust.email)
    if getattr(cust, "tax_id", ""):
        line2.append(f"Tax ID: {cust.tax_id}")
    if line2:
        billto.append(Paragraph("<br/>".join(line2), body))
    addr = cust.billing_address or cust.delivery_address or "-"
    addr_cell = [Paragraph("BILLING ADDRESS", lbl),
                 Paragraph(addr.replace("\n", "<br/>"), body)]
    bt = Table([[billto, addr_cell]], colWidths=[84 * mm, 84 * mm])
    bt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (0, 0), 0.6, LINE), ("BOX", (1, 0), (1, 0), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [bt, Spacer(1, 12)]

    # ---- Line items ----
    rows = [[Paragraph("<b>Product</b>", cellL), Paragraph("<b>SKU</b>", cellL),
             Paragraph("<b>Unit price</b>", cellR), Paragraph("<b>Qty</b>", cellR),
             Paragraph("<b>Amount</b>", cellR)]]
    for i in order.items.all():
        rows.append([
            Paragraph(i.product_name, cellL),
            Paragraph(i.sku or "", cellL),
            Paragraph(money(i.unit_price), cellR),
            Paragraph(f"{i.quantity:.0f}", cellR),
            Paragraph(money(i.line_total), cellR),
        ])
    items = Table(rows, colWidths=[72 * mm, 28 * mm, 26 * mm, 16 * mm, 26 * mm], repeatRows=1)
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#faf7f1")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [items, Spacer(1, 8)]

    # ---- Totals ----
    trows = [["Subtotal", money(order.subtotal)]]
    if order.discount_percent:
        trows.append([f"Discount ({order.discount_percent:.0f}%)", "-" + money(order.discount_amount)])
        trows.append(["Net", money(ctx["net"])])
    if site.tax_enabled and site.tax_percent:
        trows.append([f"{site.tax_label} ({site.tax_percent:.0f}%)", money(ctx["tax_amount"])])
    trows.append([f"Total ({site.currency_code})", money(ctx["grand_total"])])
    if ctx["has_invoice"]:
        trows.append(["Paid", money(ctx["amount_paid"])])
        trows.append(["Balance due", money(ctx["balance"])])
    tdata = [[Paragraph(a, cellL if idx != len(trows) - 1 else bodyb),
              Paragraph(b, cellR)] for idx, (a, b) in enumerate(trows)]
    totals = Table(tdata, colWidths=[44 * mm, 36 * mm], hAlign="RIGHT")
    grand_row = 2 + (2 if order.discount_percent else 0) + (1 if (site.tax_enabled and site.tax_percent) else 0) - 1
    totals.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, grand_row), (-1, grand_row), 1.2, DARK),
        ("FONTNAME", (0, grand_row), (-1, grand_row), "Helvetica-Bold"),
        ("FONTSIZE", (0, grand_row), (-1, grand_row), 11),
    ]))
    story += [totals, Spacer(1, 18)]

    if order.remarks:
        story += [Paragraph("REMARKS", lbl), Paragraph(order.remarks.replace("\n", "<br/>"), body), Spacer(1, 10)]

    note = ("Prices are before " + (site.tax_label or "tax") + "; the total includes " + (site.tax_label or "tax") + "."
            if (site.tax_enabled and site.tax_percent) else "Prices are exclusive of tax.")
    story += [Spacer(1, 10), Paragraph(note + f"  Thank you for your business — {site.company_name}.",
                                       ParagraphStyle("foot", parent=small, alignment=1))]

    doc.build(story)
    return buf.getvalue()


# ---- QuickBooks-style inline line editing (with calculator expressions) ----
import ast as _ast
import operator as _operator

_CALC_OPS = {
    _ast.Add: _operator.add, _ast.Sub: _operator.sub,
    _ast.Mult: _operator.mul, _ast.Div: _operator.truediv,
    _ast.USub: _operator.neg, _ast.UAdd: _operator.pos,
}


def _safe_calc(expr):
    """Evaluate a plain arithmetic expression like '12*4', '100/2+5', '(3+1)*20'.
    Only numbers and + - * / ( ) are allowed — no names, calls or attributes."""
    expr = (expr or "").strip().lstrip("=")          # allow a leading '=' like Excel/QB
    if not expr:
        raise ValueError("empty")
    node = _ast.parse(expr, mode="eval").body

    def ev(n):
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, _ast.BinOp) and type(n.op) in _CALC_OPS:
            return _CALC_OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, _ast.UnaryOp) and type(n.op) in _CALC_OPS:
            return _CALC_OPS[type(n.op)](ev(n.operand))
        raise ValueError("unsupported expression")

    return ev(node)


@role_required(*ALL_STAFF)
def order_line_update(request, pk):
    """AJAX: update one order line's quantity or unit price. The posted value may
    be a number or a calculation (evaluated safely server-side). Returns the
    recomputed line total and order totals."""
    from core.models import SiteSetting
    order = get_object_or_404(Order, pk=pk)
    if order.salesperson_id != request.user.id and not request.user.is_admin_role:
        return JsonResponse({"ok": False, "error": "You can't edit this order."}, status=403)
    if not order.is_open:
        return JsonResponse({"ok": False, "error": "This order can no longer be edited."}, status=400)

    field = request.POST.get("field")
    it = order.items.filter(pk=request.POST.get("line_id")).first()
    if not it or field not in ("qty", "price"):
        return JsonResponse({"ok": False, "error": "Bad request."}, status=400)

    try:
        raw = _safe_calc(request.POST.get("value", ""))
        val = Decimal(str(raw)).quantize(Decimal("0.01"))
    except ZeroDivisionError:
        return JsonResponse({"ok": False, "error": "Can't divide by zero."}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "Enter a number or a calc like 12*4."}, status=400)
    if val < 0:
        return JsonResponse({"ok": False, "error": "Value can't be negative."}, status=400)

    if field == "qty":
        it.quantity = val
        it.save(update_fields=["quantity"])
    else:
        it.unit_price = val
        it.save(update_fields=["unit_price"])

    site = SiteSetting.get()
    net = order.total
    if site.tax_enabled and site.tax_percent:
        tax = (net * site.tax_percent / Decimal("100")).quantize(Decimal("0.01"))
    else:
        tax = Decimal("0.00")
    qd = it.quantity
    qty_disp = f"{qd:.0f}" if qd == qd.to_integral_value() else f"{qd:.2f}"
    return JsonResponse({
        "ok": True,
        "qty": qty_disp,
        "unit_price": f"{it.unit_price:.2f}",
        "line_total": f"{it.line_total:.2f}",
        "subtotal": f"{order.subtotal:.2f}",
        "discount": f"{order.discount_amount:.2f}",
        "net": f"{net:.2f}",
        "tax": f"{tax:.2f}",
        "grand_total": f"{(net + tax):.2f}",
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