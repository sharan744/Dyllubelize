from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import Role
from core.permissions import role_required
from orders.models import Order, OrderStatus
from .models import Return, ReturnLine, ReturnPhoto

# Warehouse-facing roles (admin always allowed)
RETURN_ROLES = (Role.DISPATCH, Role.DELIVERY)


def _dec(value):
    try:
        d = Decimal(str(value or "0"))
        return d if d > 0 else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


@role_required(*RETURN_ROLES)
def return_list(request):
    returns = Return.objects.select_related("order__customer").prefetch_related("lines")
    return render(request, "returnsapp/return_list.html", {"returns": returns})


@role_required(*RETURN_ROLES)
def return_create(request):
    order_id = request.GET.get("order")

    # Step 1 — choose the order the goods came back from
    if not order_id:
        eligible = (Order.objects
                    .filter(status__in=[OrderStatus.DISPATCHED, OrderStatus.DELIVERED,
                                        OrderStatus.COMPLETED])
                    .select_related("customer").order_by("-created_at"))
        return render(request, "returnsapp/return_choose.html", {"orders": eligible})

    order = get_object_or_404(Order.objects.select_related("customer"), pk=order_id)

    if request.method == "POST":
        ret = Return.objects.create(
            order=order,
            reason=request.POST.get("reason", Return.Reason.DAMAGED),
            reason_note=request.POST.get("reason_note", "")[:255],
            notes=request.POST.get("notes", ""),
            created_by=request.user,
        )
        any_line = False
        for it in order.items.select_related("product"):
            good = _dec(request.POST.get(f"good_{it.id}"))
            damaged = _dec(request.POST.get(f"damaged_{it.id}"))
            # never accept more than was ordered on that line
            cap = it.quantity
            if good + damaged > cap:
                # trim damaged first, then good, to fit the cap
                overflow = good + damaged - cap
                damaged = max(Decimal("0"), damaged - overflow)
                overflow = good + damaged - cap
                good = max(Decimal("0"), good - overflow)
            if good + damaged > 0:
                ReturnLine.objects.create(
                    ret=ret, product=it.product, product_name=it.product_name,
                    sku=it.sku, unit=it.unit, unit_price=it.unit_price,
                    good_qty=good, damaged_qty=damaged,
                    note=request.POST.get(f"note_{it.id}", "")[:255],
                )
                any_line = True

        if not any_line:
            ret.delete()
            messages.error(request, "Enter a good or damaged quantity for at least one item.")
            return redirect(f"/returns/new/?order={order.pk}")

        for f in request.FILES.getlist("photos"):
            ReturnPhoto.objects.create(ret=ret, image=f)

        messages.success(request, f"{ret.rma_no} created. Review it, then process to update stock.")
        return redirect("return_detail", pk=ret.pk)

    return render(request, "returnsapp/return_form.html", {"order": order})


@role_required(*RETURN_ROLES)
def return_detail(request, pk):
    ret = get_object_or_404(
        Return.objects.select_related("order__customer", "created_by", "processed_by")
        .prefetch_related("lines", "photos"), pk=pk
    )
    return render(request, "returnsapp/return_detail.html", {"ret": ret})


@role_required(*RETURN_ROLES)
def return_process(request, pk):
    ret = get_object_or_404(Return, pk=pk)
    if request.method == "POST" and ret.status == Return.Status.OPEN:
        ret.process(user=request.user)
        messages.success(request, f"{ret.rma_no} processed — good units restocked, "
                                  f"damaged units written off.")
    return redirect("return_detail", pk=pk)


# ============================================================
# Credit note for a return (printable view + PDF) — documents the
# returned goods against the original order/invoice.
# ============================================================
def _credit_note_context(ret):
    from core.models import SiteSetting
    site = SiteSetting.get()
    order = ret.order
    net = ret.total_value
    if site.tax_enabled and site.tax_percent:
        tax_amount = (net * site.tax_percent / Decimal("100")).quantize(Decimal("0.01"))
    else:
        tax_amount = Decimal("0.00")
    total = net + tax_amount
    inv = getattr(order, "invoice", None)
    orig_invoice = inv.number if inv is not None else order.order_no
    cn_number = ret.rma_no.replace("RMA", "CN") if ret.rma_no else f"CN-{ret.pk}"
    date = ret.processed_at or ret.created_at
    return {
        "ret": ret, "site": site, "order": order,
        "cn_number": cn_number, "orig_invoice": orig_invoice, "date": date,
        "net": net, "tax_amount": tax_amount, "total": total,
    }


@role_required(*RETURN_ROLES)
def return_credit_note(request, pk):
    ret = get_object_or_404(
        Return.objects.select_related("order__customer", "processed_by")
        .prefetch_related("lines"), pk=pk)
    return render(request, "returnsapp/credit_note.html", _credit_note_context(ret))


@role_required(*RETURN_ROLES)
def return_credit_note_pdf(request, pk):
    from django.http import HttpResponse
    ret = get_object_or_404(
        Return.objects.select_related("order__customer", "processed_by")
        .prefetch_related("lines"), pk=pk)
    ctx = _credit_note_context(ret)
    resp = HttpResponse(_render_credit_note_pdf(ctx), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="CreditNote-{ctx["cn_number"]}.pdf"'
    return resp


def _render_credit_note_pdf(ctx):
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)

    ret = ctx["ret"]
    order = ctx["order"]
    site = ctx["site"]
    cust = order.customer
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
                            title=f"Credit Note {ctx['cn_number']}")
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
    co_cell = [Paragraph(site.tagline or "", tag), Paragraph(site.company_name or "", h_co)]
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
        co_cell.append(Paragraph("<br/>".join(info), small))

    meta_tbl = Table([
        [Paragraph("CREDIT NOTE", titleR)],
        [Paragraph(ctx["cn_number"], dnoR)],
        [Paragraph(
            f"Date: <b>{ctx['date']:%d %b %Y}</b><br/>"
            f"Against invoice: <b>{ctx['orig_invoice']}</b><br/>"
            f"Order: <b>{order.order_no}</b><br/>"
            f"RMA: <b>{ret.rma_no}</b>", metaR)],
    ], colWidths=[72 * mm])
    meta_tbl.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    head = Table([[co_cell, meta_tbl]], colWidths=[96 * mm, 72 * mm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 2, DARK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [head, Spacer(1, 10)]

    credit_to = [Paragraph("CREDIT TO", lbl),
                 Paragraph(cust.company_name or cust.name or "", bodyb)]
    line2 = []
    if cust.company_name and cust.name:
        line2.append(f"Attn: {cust.name}")
    if cust.mobile:
        line2.append(cust.mobile)
    if getattr(cust, "tax_id", ""):
        line2.append(f"Tax ID: {cust.tax_id}")
    if line2:
        credit_to.append(Paragraph("<br/>".join(line2), body))
    reason_cell = [Paragraph("REASON", lbl),
                   Paragraph(ret.get_reason_display() + (f" — {ret.reason_note}" if ret.reason_note else ""), body)]
    bt = Table([[credit_to, reason_cell]], colWidths=[84 * mm, 84 * mm])
    bt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (0, 0), 0.6, LINE), ("BOX", (1, 0), (1, 0), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [bt, Spacer(1, 12)]

    rows = [[Paragraph("<b>Product</b>", cellL), Paragraph("<b>SKU</b>", cellL),
             Paragraph("<b>Unit price</b>", cellR), Paragraph("<b>Qty returned</b>", cellR),
             Paragraph("<b>Amount</b>", cellR)]]
    for l in ret.lines.all():
        rows.append([
            Paragraph(l.product_name, cellL),
            Paragraph(l.sku or "", cellL),
            Paragraph(money(l.unit_price), cellR),
            Paragraph(f"{l.quantity:.0f}", cellR),
            Paragraph(money(l.line_value), cellR),
        ])
    items = Table(rows, colWidths=[70 * mm, 28 * mm, 26 * mm, 22 * mm, 26 * mm], repeatRows=1)
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

    trows = [["Subtotal credited", money(ctx["net"])]]
    if site.tax_enabled and site.tax_percent:
        trows.append([f"{site.tax_label} ({site.tax_percent:.0f}%)", money(ctx["tax_amount"])])
    trows.append([f"Total credit ({site.currency_code})", money(ctx["total"])])
    tdata = [[Paragraph(a, cellL if i != len(trows) - 1 else bodyb), Paragraph(b, cellR)]
             for i, (a, b) in enumerate(trows)]
    totals = Table(tdata, colWidths=[48 * mm, 34 * mm], hAlign="RIGHT")
    gr = len(trows) - 1
    totals.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, gr), (-1, gr), 1.2, DARK),
        ("FONTNAME", (0, gr), (-1, gr), "Helvetica-Bold"),
        ("FONTSIZE", (0, gr), (-1, gr), 11),
    ]))
    story += [totals, Spacer(1, 16)]
    story += [Paragraph(
        f"This credit note records goods returned against invoice {ctx['orig_invoice']}. "
        f"— {site.company_name}.", ParagraphStyle("foot", parent=small, alignment=1))]

    doc.build(story)
    return buf.getvalue()