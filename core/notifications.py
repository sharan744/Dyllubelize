"""
Best-effort notifications. Never raises — a failed send must not break a request.

Sends professional, itemised emails (HTML with a plain-text fallback) that list
each product, quantity, unit, price and the order totals.

- Email backend comes from settings (Gmail SMTP, or console).
- WhatsApp is handled in templates via click-to-send wa.me links.
"""
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape


def _site():
    try:
        from core.models import SiteSetting
        return SiteSetting.get()
    except Exception:
        return None


def _money(v, sym):
    try:
        return f"{sym}{Decimal(str(v)):,.2f}"
    except Exception:
        return f"{sym}{v}"


# ---------- body builders ----------
def _items_text(order, sym):
    lines = []
    for it in order.items.all():
        lines.append(
            f"  - {it.product_name} ({it.sku}) : "
            f"{it.quantity:g} {it.unit} x {_money(it.unit_price, sym)} "
            f"= {_money(it.line_total, sym)}")
    return "\n".join(lines) if lines else "  (no items)"


def _totals_text(order, sym):
    out = [f"  Subtotal: {_money(order.subtotal, sym)}"]
    if order.discount_percent:
        out.append(f"  Discount ({order.discount_percent:g}%): -{_money(order.discount_amount, sym)}")
    out.append(f"  Total: {_money(order.total, sym)}")
    return "\n".join(out)


def _text_body(order, intro, sym, sign):
    return (f"{intro}\n\n"
            f"Order: {order.order_no}\n"
            f"Customer: {order.customer}\n\n"
            f"Items:\n{_items_text(order, sym)}\n\n"
            f"{_totals_text(order, sym)}\n\n"
            f"{sign}")


def _html_body(order, intro, sym, company, sign_html):
    rows = ""
    for it in order.items.all():
        rows += (
            "<tr>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{escape(it.product_name)}"
            f"<br><span style='color:#8a8594;font-size:12px'>{escape(it.sku)}</span></td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee'>{it.quantity:g} {escape(it.unit)}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee;text-align:right'>{_money(it.unit_price, sym)}</td>"
            f"<td style='padding:8px 10px;border-bottom:1px solid #eee;text-align:right'><b>{_money(it.line_total, sym)}</b></td>"
            "</tr>")
    disc_row = ""
    if order.discount_percent:
        disc_row = (f"<tr><td colspan='3' style='padding:4px 10px;text-align:right;color:#6b6577'>"
                    f"Discount ({order.discount_percent:g}%)</td>"
                    f"<td style='padding:4px 10px;text-align:right'>-{_money(order.discount_amount, sym)}</td></tr>")
    return f"""\
<div style="font-family:Arial,Segoe UI,sans-serif;max-width:600px;margin:0 auto;color:#26232c">
  <div style="background:#17161f;color:#fff;padding:18px 22px;border-radius:10px 10px 0 0">
    <div style="font-size:18px;font-weight:800;letter-spacing:.5px">{escape(company)}</div>
    <div style="color:#caa04e;font-size:12px;letter-spacing:2px;text-transform:uppercase">Distribution &amp; Supply</div>
  </div>
  <div style="border:1px solid #e6ded0;border-top:none;border-radius:0 0 10px 10px;padding:22px">
    <p style="margin:0 0 14px">{escape(intro)}</p>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <tr>
        <td style="color:#6b6577">Order</td><td style="text-align:right;font-weight:700">{escape(order.order_no)}</td>
      </tr>
      <tr>
        <td style="color:#6b6577">Customer</td><td style="text-align:right">{escape(str(order.customer))}</td>
      </tr>
    </table>
    <table style="width:100%;border-collapse:collapse;margin-top:16px;font-size:14px">
      <thead>
        <tr style="background:#f4f1ea">
          <th style="padding:8px 10px;text-align:left;font-size:12px;text-transform:uppercase;color:#6b6577">Product</th>
          <th style="padding:8px 10px;text-align:left;font-size:12px;text-transform:uppercase;color:#6b6577">Qty / Unit</th>
          <th style="padding:8px 10px;text-align:right;font-size:12px;text-transform:uppercase;color:#6b6577">Price</th>
          <th style="padding:8px 10px;text-align:right;font-size:12px;text-transform:uppercase;color:#6b6577">Amount</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
      <tfoot>
        <tr><td colspan="3" style="padding:8px 10px;text-align:right;color:#6b6577">Subtotal</td>
            <td style="padding:8px 10px;text-align:right">{_money(order.subtotal, sym)}</td></tr>
        {disc_row}
        <tr><td colspan="3" style="padding:10px;text-align:right;font-weight:800;border-top:2px solid #17161f">Total</td>
            <td style="padding:10px;text-align:right;font-weight:800;border-top:2px solid #17161f">{_money(order.total, sym)}</td></tr>
      </tfoot>
    </table>
    <p style="margin:18px 0 0;color:#6b6577;font-size:13px">{sign_html}</p>
  </div>
</div>"""


def _send(subject, text_body, html_body, recipients):
    recipients = [r for r in recipients if r]
    if not recipients or not getattr(settings, "NOTIFY_ENABLED", True):
        return
    try:
        msg = EmailMultiAlternatives(subject, text_body,
                                     settings.DEFAULT_FROM_EMAIL, recipients)
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=True)
    except Exception:
        pass


# ---------- public notifications ----------
def notify_new_order(order):
    try:
        from accounts.models import User, Role
        site = _site()
        sym = site.currency_symbol if site else "$"
        company = site.company_name if site else "United Distributors Ltd"
        leads = list(User.objects.filter(role=Role.TEAM_LEAD, is_active=True)
                     .exclude(email="").values_list("email", flat=True))
        who = order.salesperson.display_name if order.salesperson else "A salesperson"
        intro = f"{who} submitted a new order for review. Details below."
        sign = "Please review and confirm it in the Review Queue."
        _send(f"New order {order.order_no} awaiting review",
              _text_body(order, intro, sym, sign),
              _html_body(order, intro, sym, company, sign),
              leads)
    except Exception:
        pass


def notify_dispatched(order):
    try:
        email = getattr(order.customer, "email", "")
        if not email:
            return
        site = _site()
        sym = site.currency_symbol if site else "$"
        company = site.company_name if site else "United Distributors Ltd"
        intro = (f"Dear {order.customer.name}, your order has been dispatched and is "
                 f"on its way. Here is a summary of your order.")
        sign = f"Thank you for your business,<br>{escape(company)}"
        sign_txt = f"Thank you for your business,\n{company}"
        _send(f"Your order {order.order_no} is on its way",
              _text_body(order, intro, sym, sign_txt),
              _html_body(order, intro, sym, company, sign),
              [email])
    except Exception:
        pass


def notify_delivered(order):
    try:
        email = getattr(order.customer, "email", "")
        if not email:
            return
        site = _site()
        sym = site.currency_symbol if site else "$"
        company = site.company_name if site else "United Distributors Ltd"
        intro = (f"Dear {order.customer.name}, your order has been delivered. "
                 f"Here is a summary for your records.")
        sign = f"Thank you for choosing {escape(company)}."
        sign_txt = f"Thank you for choosing {company}."
        _send(f"Order {order.order_no} delivered",
              _text_body(order, intro, sym, sign_txt),
              _html_body(order, intro, sym, company, sign),
              [email])
    except Exception:
        pass


# ---------- expiry alerts (perishable stock) ----------
def notify_expiring(batches, recipients=None):
    """Email admin + team a list of batches that are expiring soon or expired.

    `batches` is an iterable of catalogue.StockBatch. Returns the number of
    recipients emailed (0 if nothing to send).
    """
    try:
        batches = [b for b in batches if b.qty_remaining and b.expiry_date]
        if not batches:
            return 0
        from accounts.models import User, Role
        site = _site()
        company = site.company_name if site else "United Distributors Ltd"
        if recipients is None:
            recipients = list(
                User.objects.filter(is_active=True)
                .filter(role__in=[Role.ADMIN, Role.TEAM_LEAD, Role.PROCESSING])
                .exclude(email="").values_list("email", flat=True))
        if not recipients:
            return 0

        # sort earliest expiry first
        batches = sorted(batches, key=lambda b: b.expiry_date)
        text_rows, html_rows = [], []
        for b in batches:
            d = b.days_to_expiry
            when = "EXPIRED" if d is not None and d < 0 else f"{d} day(s) left"
            text_rows.append(
                f"  - {b.product.name} ({b.product.sku}): {b.qty_remaining:g} left, "
                f"expiry {b.expiry_date} [{when}]")
            colour = "#c92a2a" if (d is not None and d < 0) else "#b8791b"
            html_rows.append(
                f"<tr><td style='padding:6px 10px'>{escape(b.product.name)} "
                f"<span style='color:#888'>({escape(b.product.sku)})</span></td>"
                f"<td style='padding:6px 10px;text-align:right'>{b.qty_remaining:g}</td>"
                f"<td style='padding:6px 10px'>{b.expiry_date}</td>"
                f"<td style='padding:6px 10px;color:{colour};font-weight:600'>{when}</td></tr>")

        subject = f"[{company}] {len(batches)} stock batch(es) nearing expiry"
        text_body = (
            "The following perishable stock batches are expired or nearing expiry.\n"
            "They are sold earliest-expiry-first, so please prioritise or clear them.\n\n"
            + "\n".join(text_rows)
            + "\n\nOpen the app → Warehouse → Expiring Soon for details.")
        html_body = (
            f"<div style='font-family:Inter,Arial,sans-serif;color:#17161f'>"
            f"<h2 style='margin:0 0 6px'>Stock nearing expiry</h2>"
            f"<p style='color:#555;margin:0 0 14px'>Sold earliest-expiry-first (FEFO) — "
            f"please prioritise or clear these batches.</p>"
            f"<table style='border-collapse:collapse;font-size:14px'>"
            f"<thead><tr style='background:#f4f1ea'>"
            f"<th style='padding:6px 10px;text-align:left'>Product</th>"
            f"<th style='padding:6px 10px;text-align:right'>Qty left</th>"
            f"<th style='padding:6px 10px;text-align:left'>Expiry</th>"
            f"<th style='padding:6px 10px;text-align:left'>Status</th></tr></thead>"
            f"<tbody>{''.join(html_rows)}</tbody></table></div>")

        _send(subject, text_body, html_body, recipients)
        return len(recipients)
    except Exception:
        return 0
