import calendar
import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone

from core.permissions import role_required
from orders.models import Order, OrderStatus
from dispatchapp.models import Dispatch
from core.models import SiteSetting
from accounting.models import Invoice


@login_required
def dashboard(request):
    user = request.user
    base = Order.objects.all()
    if user.is_sales:
        base = base.filter(salesperson=user)

    def count(status):
        return base.filter(status=status).count()

    stats = {
        "total": base.count(),
        "new": count(OrderStatus.SUBMITTED),
        "pending_review": base.filter(
            status__in=[OrderStatus.SUBMITTED, OrderStatus.TEAM_LEAD_REVIEW]
        ).count(),
        "confirmed": count(OrderStatus.CONFIRMED),
        "processing": count(OrderStatus.PROCESSING),
        "ready": count(OrderStatus.READY),
        "dispatched": count(OrderStatus.DISPATCHED),
        "delivered": base.filter(
            status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED]
        ).count(),
        "cancelled": base.filter(
            status__in=[OrderStatus.REJECTED, OrderStatus.CANCELLED]
        ).count(),
    }

    # revenue from completed/delivered orders
    revenue = 0
    for o in base.filter(status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED]):
        revenue += float(o.total)

    recent = base.select_related("customer", "salesperson")[:8]

    # simple status distribution for the chart
    chart = [
        {"label": "New", "value": stats["new"]},
        {"label": "Review", "value": stats["pending_review"]},
        {"label": "Confirmed", "value": stats["confirmed"]},
        {"label": "Processing", "value": stats["processing"]},
        {"label": "Ready", "value": stats["ready"]},
        {"label": "Dispatched", "value": stats["dispatched"]},
        {"label": "Delivered", "value": stats["delivered"]},
    ]
    chart_max = max([c["value"] for c in chart] + [1])

    # role-specific action items
    todo = _role_todo(user)

    # low-stock (warehouse roles)
    low_stock = []
    if user.is_processing or user.is_dispatch or user.is_admin_role:
        from django.db.models import F
        from catalogue.models import Product
        low_stock = list(Product.objects.filter(
            track_stock=True, reorder_point__gt=0,
            stock_qty__lte=F("reorder_point")).select_related("category")[:8])

    return render(request, "core/dashboard.html", {
        "low_stock": low_stock,
        "stats": stats,
        "revenue": revenue,
        "recent": recent,
        "chart": chart,
        "chart_max": chart_max,
        "todo": todo,
    })


def _role_todo(user):
    items = []
    if user.is_team_lead or user.is_admin_role:
        n = Order.objects.filter(
            status__in=[OrderStatus.SUBMITTED, OrderStatus.TEAM_LEAD_REVIEW]
        ).count()
        if n:
            items.append({"label": f"{n} order(s) awaiting your review",
                          "url": "review_queue", "tone": "amber"})
    if user.is_processing or user.is_admin_role:
        n = Order.objects.filter(status=OrderStatus.CONFIRMED).count()
        if n:
            items.append({"label": f"{n} confirmed order(s) to process",
                          "url": "processing_queue", "tone": "blue"})
    if user.is_dispatch or user.is_admin_role:
        n = Order.objects.filter(status=OrderStatus.READY).count()
        if n:
            items.append({"label": f"{n} order(s) ready to dispatch",
                          "url": "dispatch_create", "tone": "violet"})
    if user.is_delivery or user.is_admin_role:
        n = Order.objects.filter(status=OrderStatus.DISPATCHED).count()
        if n:
            items.append({"label": f"{n} delivery(ies) to confirm",
                          "url": "delivery_queue", "tone": "green"})
    return items


# ============================================================
# Accounting visibility helpers
# ============================================================
def _accounts_follow_invoice_visibility():
    return bool(SiteSetting.get().accounts_follow_invoice_visibility)


def _orders_for_accounting(queryset):
    """When enabled, keep only orders whose invoice is selected for UI."""
    if _accounts_follow_invoice_visibility():
        return queryset.filter(invoice__show_in_ui=True)
    return queryset


# ============================================================
# Accounting (admin only)
# ============================================================
@role_required()  # admin only
def accounting(request):
    period = request.GET.get("period", "monthly")
    if period not in ("weekly", "monthly", "yearly"):
        period = "monthly"

    today = timezone.localdate()

    realized = _orders_for_accounting(
        Order.objects
        .filter(status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        .prefetch_related("items")
    )
    voided = _orders_for_accounting(
        Order.objects
        .filter(status__in=[OrderStatus.CANCELLED, OrderStatus.REJECTED])
        .prefetch_related("items")
    )

    def rev_date(o):
        d = o.completed_at or o.confirmed_at or o.created_at
        return timezone.localtime(d).date()

    # Build the time buckets
    buckets = []  # (label, start_date, end_date)
    if period == "weekly":
        monday = today - datetime.timedelta(days=today.weekday())
        for i in range(7, -1, -1):
            ws = monday - datetime.timedelta(weeks=i)
            buckets.append((ws.strftime("%d %b"), ws, ws + datetime.timedelta(days=6)))
    elif period == "yearly":
        for i in range(5, -1, -1):
            y = today.year - i
            buckets.append((str(y), datetime.date(y, 1, 1), datetime.date(y, 12, 31)))
    else:  # monthly — last 12 months
        y, m = today.year, today.month
        months = []
        for i in range(11, -1, -1):
            mm, yy = m - i, y
            while mm <= 0:
                mm += 12
                yy -= 1
            months.append((yy, mm))
        for yy, mm in months:
            last = calendar.monthrange(yy, mm)[1]
            buckets.append((datetime.date(yy, mm, 1).strftime("%b %y"),
                            datetime.date(yy, mm, 1), datetime.date(yy, mm, last)))

    chart, table = [], []
    for label, start, end in buckets:
        total = Decimal("0.00")
        count = 0
        for o in realized:
            if start <= rev_date(o) <= end:
                total += o.total
                count += 1
        chart.append({"label": label, "value": float(total), "count": count})
        table.append({"label": label, "value": total, "count": count})

    chart_max = max([c["value"] for c in chart] + [1])
    total_rev = sum((Decimal(str(c["value"])) for c in chart), Decimal("0.00"))
    total_orders = sum(c["count"] for c in chart)
    avg = (total_rev / total_orders) if total_orders else Decimal("0.00")

    # Returns / cancellations within the shown window
    win_start, win_end = buckets[0][1], buckets[-1][2]
    returns_val = Decimal("0.00")
    returns_cnt = 0
    for o in voided:
        d = timezone.localtime(o.updated_at).date()
        if win_start <= d <= win_end:
            returns_val += o.total
            returns_cnt += 1

    # Returns register (RMA) processed within the window
    from returnsapp.models import Return
    rmas = (Return.objects.filter(status=Return.Status.COMPLETED,
                                  processed_at__date__gte=win_start,
                                  processed_at__date__lte=win_end)
            .prefetch_related("lines"))
    rma_damaged = Decimal("0.00")
    rma_restock = Decimal("0.00")
    rma_count = 0
    for r in rmas:
        rma_damaged += r.damaged_value
        rma_restock += r.restock_value
        rma_count += 1

    return render(request, "core/accounting.html", {
        "rma_damaged": rma_damaged,
        "rma_restock": rma_restock,
        "rma_count": rma_count,
        "period": period,
        "chart": chart,
        "chart_max": chart_max,
        "table": list(reversed(table)),
        "total_rev": total_rev,
        "total_orders": total_orders,
        "avg": avg,
        "returns_val": returns_val,
        "returns_cnt": returns_cnt,
        "window": {"start": win_start, "end": win_end},
    })


# ============================================================
# Reports & exports (admin only)
# ============================================================
def _parse_range(request):
    today = timezone.localdate()
    default_start = today - datetime.timedelta(days=90)
    try:
        start = datetime.date.fromisoformat(request.GET.get("from", ""))
    except ValueError:
        start = default_start
    try:
        end = datetime.date.fromisoformat(request.GET.get("to", ""))
    except ValueError:
        end = today
    return start, end


def _report_data(start, end):
    from decimal import Decimal
    from catalogue.models import Product
    orders = _orders_for_accounting(
        Order.objects
        .filter(status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        .select_related("customer", "salesperson")
        .prefetch_related("items")
    )

    def odate(o):
        d = o.completed_at or o.confirmed_at or o.created_at
        return timezone.localtime(d).date()

    by_product, by_customer, by_salesperson = {}, {}, {}
    grand = Decimal("0.00")
    for o in orders:
        if not (start <= odate(o) <= end):
            continue
        grand += o.total
        cust = str(o.customer)
        c = by_customer.setdefault(cust, {"orders": 0, "revenue": Decimal("0.00")})
        c["orders"] += 1
        c["revenue"] += o.total
        sp = o.salesperson.display_name if o.salesperson else "—"
        s = by_salesperson.setdefault(sp, {"orders": 0, "revenue": Decimal("0.00")})
        s["orders"] += 1
        s["revenue"] += o.total
        for it in o.items.all():
            pr = by_product.setdefault(it.product_name, {"sku": it.sku, "qty": Decimal("0"),
                                                         "revenue": Decimal("0.00")})
            pr["qty"] += it.quantity
            pr["revenue"] += it.line_total

    # inventory valuation (point-in-time)
    valuation = []
    val_total = Decimal("0.00")
    for p in Product.objects.filter(track_stock=True):
        v = p.stock_value
        val_total += v
        valuation.append({"name": p.name, "sku": p.sku, "stock": p.stock_qty,
                          "cost": p.cost_price, "value": v})

    def rows(d, key):
        return sorted(({"label": k, **v} for k, v in d.items()),
                      key=lambda r: r[key], reverse=True)

    return {
        "by_product": rows(by_product, "revenue"),
        "by_customer": rows(by_customer, "revenue"),
        "by_salesperson": rows(by_salesperson, "revenue"),
        "valuation": sorted(valuation, key=lambda r: r["value"], reverse=True),
        "val_total": val_total,
        "grand": grand,
    }


@role_required()  # admin only
def reports(request):
    from .models import SiteSetting
    start, end = _parse_range(request)
    data = _report_data(start, end)
    sym = SiteSetting.get().currency_symbol

    def m(v):
        return f"{sym}{v:,.2f}"

    blocks = [
        {"title": "Sales by product", "kind": "product",
         "col1": "Product", "col2": "Qty", "col3": "Revenue",
         "rows": [(r["label"], f"{r['qty']:.0f}", m(r["revenue"]), r["sku"]) for r in data["by_product"]],
         "total": m(data["grand"])},
        {"title": "Sales by salesperson", "kind": "salesperson",
         "col1": "Salesperson", "col2": "Orders", "col3": "Revenue",
         "rows": [(r["label"], str(r["orders"]), m(r["revenue"]), "") for r in data["by_salesperson"]]},
        {"title": "Sales by customer", "kind": "customer",
         "col1": "Customer", "col2": "Orders", "col3": "Revenue",
         "rows": [(r["label"], str(r["orders"]), m(r["revenue"]), "") for r in data["by_customer"]]},
        {"title": "Inventory valuation", "kind": "valuation",
         "col1": "Product", "col2": "Stock", "col3": "Value",
         "rows": [(r["name"], f"{r['stock']:.0f}", m(r["value"]), r["sku"]) for r in data["valuation"]],
         "total": m(data["val_total"])},
    ]
    return render(request, "core/reports.html", {
        "start": start, "end": end, "grand": data["grand"], "blocks": blocks,
    })


@role_required()
def report_export(request, kind):
    import csv
    from django.http import HttpResponse
    start, end = _parse_range(request)
    data = _report_data(start, end)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{kind}_{start}_{end}.csv"'
    w = csv.writer(resp)
    if kind == "product":
        w.writerow(["Product", "SKU", "Qty sold", "Revenue"])
        for r in data["by_product"]:
            w.writerow([r["label"], r["sku"], r["qty"], r["revenue"]])
    elif kind == "customer":
        w.writerow(["Customer", "Orders", "Revenue"])
        for r in data["by_customer"]:
            w.writerow([r["label"], r["orders"], r["revenue"]])
    elif kind == "salesperson":
        w.writerow(["Salesperson", "Orders", "Revenue"])
        for r in data["by_salesperson"]:
            w.writerow([r["label"], r["orders"], r["revenue"]])
    elif kind == "valuation":
        w.writerow(["Product", "SKU", "Stock", "Unit cost", "Value"])
        for r in data["valuation"]:
            w.writerow([r["name"], r["sku"], r["stock"], r["cost"], r["value"]])
        w.writerow([])
        w.writerow(["Total", "", "", "", data["val_total"]])
    else:
        w.writerow(["Unknown report"])
    return resp


# ============================================================
# Salesperson incentives (admin only)
# ============================================================
@role_required()
def incentives(request):
    from decimal import Decimal
    from .models import SiteSetting
    start, end = _parse_range(request)
    default_rate = SiteSetting.get().incentive_percent

    orders = _orders_for_accounting(
        Order.objects
        .filter(status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED])
        .select_related("salesperson")
        .prefetch_related("items")
    )

    data = {}
    for o in orders:
        d = o.completed_at or o.confirmed_at or o.created_at
        if not (start <= timezone.localtime(d).date() <= end):
            continue
        sp = o.salesperson
        key = sp.id if sp else 0
        rate = (sp.incentive_percent if sp and sp.incentive_percent is not None else default_rate)
        row = data.setdefault(key, {"name": sp.display_name if sp else "—",
                                    "rate": rate, "orders": 0,
                                    "sales": Decimal("0.00"), "margin": Decimal("0.00")})
        row["orders"] += 1
        row["sales"] += o.total
        row["margin"] += o.margin

    rows = []
    tot_sales = tot_margin = tot_inc = Decimal("0.00")
    for r in data.values():
        r["incentive"] = (r["margin"] * r["rate"] / Decimal("100")).quantize(Decimal("0.01"))
        tot_sales += r["sales"]; tot_margin += r["margin"]; tot_inc += r["incentive"]
        rows.append(r)
    rows.sort(key=lambda x: x["incentive"], reverse=True)

    return render(request, "core/incentives.html", {
        "rows": rows, "start": start, "end": end, "default_rate": default_rate,
        "tot_sales": tot_sales, "tot_margin": tot_margin, "tot_inc": tot_inc,
    })
