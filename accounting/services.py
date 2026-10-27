"""
Posting engine + default Chart of Accounts.

Every document turns into a balanced JournalEntry here. Views never touch
JournalLine directly — they call post_invoice(), receive_payment() etc. so the
ledger always balances.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from .models import (
    Account, AccountType, JournalEntry, JournalLine, JournalSource,
    Invoice, InvoiceLine, Payment, PaymentApplication, CreditNote, CreditApplication,
    Bill, BillLine, BillPayment, BillPaymentApplication, DocStatus, q,
)

Z = Decimal("0.00")

# --- Standard account codes the engine relies on -----------------------------
CODES = {
    "AR": "1200",           # Accounts Receivable
    "AP": "2000",           # Accounts Payable (to suppliers — goods only)
    "LANDED_EXP": "2100",   # Accrued landed-cost expenses (freight/duty, not the supplier)
    "TAX": "2200",          # Sales tax / GST payable
    "SALES": "4000",        # Sales income
    "RETURNS": "4900",      # Sales returns & allowances (contra-income)
    "COGS": "5000",         # Cost of goods sold
    "FREIGHT": "6400",      # Freight & delivery / PO expenses
    "SHRINK": "5100",       # Inventory shrinkage / write-off & adjustments
    "INVENTORY": "1300",    # Inventory asset
    "BANK": "1010",         # Main bank
    "CASH": "1000",         # Cash on hand
}

DEFAULT_CHART = [
    # code, name, type, is_bank, parent_code
    ("1000", "Cash on Hand", AccountType.ASSET, True, None),
    ("1010", "Bank — Belize Bank Ltd", AccountType.ASSET, True, None),
    ("1200", "Accounts Receivable", AccountType.ASSET, False, None),
    ("1300", "Inventory Asset", AccountType.ASSET, False, None),
    ("1500", "Property & Equipment", AccountType.ASSET, False, None),
    ("2000", "Accounts Payable", AccountType.LIABILITY, False, None),
    ("2100", "Accrued Landed Costs (Freight/Duty)", AccountType.LIABILITY, False, None),
    ("2200", "Sales Tax / GST Payable", AccountType.LIABILITY, False, None),
    ("2400", "Payroll Liabilities", AccountType.LIABILITY, False, None),
    ("3000", "Owner's Capital", AccountType.EQUITY, False, None),
    ("3900", "Retained Earnings", AccountType.EQUITY, False, None),
    ("4000", "Sales Income", AccountType.INCOME, False, None),
    ("4100", "Shipping & Handling Income", AccountType.INCOME, False, None),
    ("4900", "Sales Returns & Allowances", AccountType.INCOME, False, None),
    ("5000", "Cost of Goods Sold", AccountType.EXPENSE, False, None),
    ("5100", "Inventory Shrinkage & Adjustments", AccountType.EXPENSE, False, None),
    ("6000", "Operating Expenses", AccountType.EXPENSE, False, None),
    ("6100", "Rent", AccountType.EXPENSE, False, "6000"),
    ("6200", "Salaries & Wages", AccountType.EXPENSE, False, "6000"),
    ("6300", "Utilities", AccountType.EXPENSE, False, "6000"),
    ("6400", "Freight & Delivery", AccountType.EXPENSE, False, "6000"),
    ("6500", "Office & Admin", AccountType.EXPENSE, False, "6000"),
    ("6600", "Marketing & Advertising", AccountType.EXPENSE, False, "6000"),
    ("6900", "Bank Charges", AccountType.EXPENSE, False, "6000"),
]


def acc(code):
    return Account.objects.filter(code=code).first()


def ensure_chart():
    """Create the default chart of accounts if it doesn't exist yet."""
    created = 0
    for code, name, atype, is_bank, _parent in DEFAULT_CHART:
        _, was = Account.objects.get_or_create(
            code=code, defaults={"name": name, "type": atype, "is_bank": is_bank})
        created += int(was)
    # wire parents in a second pass
    for code, name, atype, is_bank, parent_code in DEFAULT_CHART:
        if parent_code:
            a = acc(code)
            p = acc(parent_code)
            if a and p and a.parent_id != p.id:
                a.parent = p
                a.save(update_fields=["parent"])
    return created


# --- low-level -------------------------------------------------------------
def _entry(date, memo, source, source_id, user, lines, reference=""):
    """lines: list of (account, debit, credit, memo, customer, supplier)."""
    je = JournalEntry.objects.create(
        date=date, memo=memo, source=source, source_id=source_id,
        reference=reference, created_by=user, posted=True)
    for account, debit, credit, lmemo, customer, supplier in lines:
        JournalLine.objects.create(
            entry=je, account=account, debit=q(debit), credit=q(credit),
            memo=lmemo or "", customer=customer, supplier=supplier)
    return je


def _void_entry(je):
    if je:
        je.lines.all().delete()
        je.delete()


# --- Invoices --------------------------------------------------------------
@transaction.atomic
def post_invoice(invoice, user=None):
    """Dr A/R ; Cr Sales (per line) ; Cr Tax payable. Also books COGS if costs known."""
    _void_entry(invoice.journal)
    ar = acc(CODES["AR"])
    tax_acc = acc(CODES["TAX"])
    sales_default = acc(CODES["SALES"])

    lines = [(ar, invoice.total, Z, f"Invoice {invoice.number}",
              invoice.customer, None)]
    for il in invoice.lines.all():
        inc = il.income_account or sales_default
        lines.append((inc, Z, il.amount, il.description, None, None))
    if invoice.tax and tax_acc:
        lines.append((tax_acc, Z, invoice.tax, "Sales tax", None, None))

    # Cost of goods sold (from linked order item costs, if available)
    cogs_total = Z
    if invoice.order_id:
        try:
            cogs_total = q(invoice.order.total_cost)
        except Exception:
            cogs_total = Z
    if cogs_total > 0:
        cogs = acc(CODES["COGS"])
        inv_asset = acc(CODES["INVENTORY"])
        if cogs and inv_asset:
            lines.append((cogs, cogs_total, Z, "Cost of goods sold", None, None))
            lines.append((inv_asset, Z, cogs_total, "Inventory reduction", None, None))

    je = _entry(invoice.date, f"Invoice {invoice.number} — {invoice.customer}",
                JournalSource.INVOICE, invoice.id, user, lines,
                reference=invoice.number)
    invoice.journal = je
    if invoice.status == DocStatus.DRAFT:
        invoice.status = DocStatus.OPEN
    invoice.save(update_fields=["journal", "status"])
    invoice.recalc_status()
    return je


@transaction.atomic
def void_invoice(invoice, user=None):
    _void_entry(invoice.journal)
    invoice.journal = None
    invoice.status = DocStatus.VOID
    invoice.save(update_fields=["journal", "status"])


def invoice_from_order(order, user=None, tax_percent=None, terms_days=30, post=True):
    """Build (and optionally post) an Invoice mirroring an order's priced lines."""
    from core.models import SiteSetting
    if hasattr(order, "invoice") and order.invoice:
        return order.invoice
    if tax_percent is None:
        # Honour the order's own GST / Non choice.
        if getattr(order, "tax_mode", "GST") == "NON":
            tax_percent = Decimal("0")
        else:
            site = SiteSetting.get()
            tax_percent = site.tax_percent if getattr(site, "tax_enabled", False) else Decimal("0")
    inv = Invoice.objects.create(
        customer=order.customer, order=order, date=timezone.localdate(),
        terms_days=terms_days, tax_percent=tax_percent or 0,
        memo=f"Order {order.order_no}", created_by=user, status=DocStatus.DRAFT,
        show_in_ui=True)   # order invoices are visible in the Invoices & A/R list
    sales = acc(CODES["SALES"])
    for it in order.items.all():
        prod = getattr(it, "product", None)
        InvoiceLine.objects.create(
            invoice=inv, product=prod, income_account=sales,
            description=it.product_name, quantity=it.quantity, unit_price=it.unit_price,
            taxable=getattr(prod, "taxable", True))
    if post:
        post_invoice(inv, user=user)
    return inv


# --- Customer payments -----------------------------------------------------
@transaction.atomic
def post_payment(payment, user=None):
    """Dr Bank/Cash ; Cr A/R."""
    _void_entry(payment.journal)
    ar = acc(CODES["AR"])
    lines = [
        (payment.deposit_account, payment.amount, Z,
         f"Receipt {payment.number}", payment.customer, None),
        (ar, Z, payment.amount, f"Receipt {payment.number}", payment.customer, None),
    ]
    je = _entry(payment.date, f"Payment {payment.number} — {payment.customer}",
                JournalSource.PAYMENT, payment.id, user, lines,
                reference=payment.reference or payment.number)
    payment.journal = je
    payment.save(update_fields=["journal"])
    for ap in payment.applications.all():
        ap.invoice.recalc_status()
    return je


# --- Credit notes ----------------------------------------------------------
@transaction.atomic
def post_credit_note(cn, user=None):
    """Dr Sales Returns ; Cr A/R (reduces what the customer owes)."""
    _void_entry(cn.journal)
    ar = acc(CODES["AR"])
    returns = acc(CODES["RETURNS"])
    lines = [
        (returns, cn.amount, Z, f"Credit {cn.number}", None, None),
        (ar, Z, cn.amount, f"Credit {cn.number}", cn.customer, None),
    ]
    je = _entry(cn.date, f"Credit note {cn.number} — {cn.customer}",
                JournalSource.CREDIT, cn.id, user, lines, reference=cn.number)
    cn.journal = je
    cn.save(update_fields=["journal"])
    for ap in cn.applications.all():
        ap.invoice.recalc_status()
    return je


# --- Vendor bills ----------------------------------------------------------
@transaction.atomic
def post_bill(bill, user=None):
    """Dr Expense/Asset (per line) ; Cr A/P."""
    _void_entry(bill.journal)
    ap = acc(CODES["AP"])
    lines = []
    for bl in bill.lines.all():
        lines.append((bl.account, bl.amount, Z, bl.description, None, bill.supplier))
    lines.append((ap, Z, bill.total, f"Bill {bill.number}", None, bill.supplier))
    je = _entry(bill.date, f"Bill {bill.number} — {bill.supplier}",
                JournalSource.BILL, bill.id, user, lines, reference=bill.number)
    bill.journal = je
    if bill.status == DocStatus.DRAFT:
        bill.status = DocStatus.OPEN
    bill.save(update_fields=["journal", "status"])
    bill.recalc_status()
    return je


@transaction.atomic
def post_bill_payment(bp, user=None):
    """Dr A/P ; Cr Bank/Cash."""
    _void_entry(bp.journal)
    ap = acc(CODES["AP"])
    lines = [
        (ap, bp.amount, Z, f"Payment {bp.number}", None, bp.supplier),
        (bp.pay_from, Z, bp.amount, f"Payment {bp.number}", None, bp.supplier),
    ]
    je = _entry(bp.date, f"Bill payment {bp.number} — {bp.supplier}",
                JournalSource.BILLPAY, bp.id, user, lines,
                reference=bp.reference or bp.number)
    bp.journal = je
    bp.save(update_fields=["journal"])
    for a in bp.applications.all():
        a.bill.recalc_status()
    return je


@transaction.atomic
def void_bill_payment(bp, user=None):
    """Reverse a supplier bill payment: remove its ledger entry and the payment
    record, then restore the balance on the bill(s) it was applied to."""
    bills = [a.bill for a in bp.applications.all()]
    _void_entry(bp.journal)
    bp.journal = None
    bp.delete()               # cascades its applications
    for b in bills:
        b.recalc_status()


# ============================================================
# Inventory ↔ Accounts linkage (QuickBooks-style perpetual inventory)
#
#   • Receiving a Purchase Order  → Dr Inventory Asset ; Cr Accounts Payable
#     (via an auto-created vendor Bill, so it also shows in A/P & Pay Bills)
#   • Selling (order delivered)   → an invoice is auto-generated:
#        Dr A/R ; Cr Sales ; Cr Tax   and   Dr COGS ; Cr Inventory Asset
#   • Damage / write-off          → Dr Inventory Shrinkage ; Cr Inventory Asset
# ============================================================
@transaction.atomic
def bill_from_po(po, user=None, post=True):
    """On PO receipt, book the stock into Inventory Asset and raise A/P."""
    ensure_chart()
    if po.bills.exists():                      # already billed — don't double count
        return po.bills.first()
    inv_asset = acc(CODES["INVENTORY"])
    if not inv_asset:
        return None
    bill = Bill.objects.create(
        supplier=po.supplier, purchase_order=po, number=po.po_no,
        date=timezone.localdate(), memo=f"Goods received — {po.po_no}",
        status=DocStatus.DRAFT, created_by=user)
    rate = getattr(po, "exchange_rate", None) or Decimal("1")
    # Does this PO use the USD landed-cost model? If so, each line's unit_cost
    # ALREADY has the expenses apportioned into it, so we must not add the
    # expenses a second time. We book the goods at their supplier (pre-expense)
    # value and capitalize the expenses as separate Inventory lines — the two
    # together equal the landed cost, with no double counting.
    uses_landed = any(q(getattr(l, "unit_cost_usd", 0)) > 0 for l in po.lines.all())
    # --- Supplier bill = GOODS ONLY (that's all the supplier is owed). ---
    for l in po.lines.select_related("product").all():
        qty = q(l.qty_received or l.qty_ordered)
        if uses_landed and q(getattr(l, "unit_cost_usd", 0)) > 0:
            unit = q(q(l.unit_cost_usd) * rate)   # supplier price in BZD, pre-expense
        else:
            unit = q(l.unit_cost)                 # plain BZD cost (old-style PO)
        amt = q(qty * unit)
        if amt <= 0:
            continue
        name = l.product.name if l.product_id else "Item"
        BillLine.objects.create(
            bill=bill, account=inv_asset,
            description=f"{name} × {qty:g} @ {unit}", amount=amt)
    if not bill.lines.exists():
        bill.delete()
        return None
    if post:
        post_bill(bill, user=user)             # Dr Inventory Asset ; Cr A/P (goods only)

    # --- PO expenses (freight, duty, insurance …) are NOT the supplier's; they are
    # company costs owed to other parties. Capitalize them into Inventory so stock
    # stays at landed cost, with the other side in a separate "Accrued Landed Costs"
    # liability — recorded against this PO, not on the supplier bill. ---
    _post_po_expenses(po, bill, user=user)
    return bill


def _po_expense_entries(po):
    """Journal entries that carry a PO's landed-cost expenses (for void/cleanup)."""
    return JournalEntry.objects.filter(
        source=JournalSource.BILL, source_id=po.id,
        reference=f"{po.po_no}-EXP")


@transaction.atomic
def _post_po_expenses(po, bill=None, user=None):
    """Book the PO's expenses: Dr Inventory Asset ; Cr Accrued Landed Costs.
    Idempotent — re-voids any previous expense entry for this PO first."""
    for je in list(_po_expense_entries(po)):
        _void_entry(je)
    inv_asset = acc(CODES["INVENTORY"])
    accrued = acc(CODES["LANDED_EXP"])
    if not inv_asset or not accrued:
        return None
    rate = getattr(po, "exchange_rate", None) or Decimal("1")
    lines, total = [], Z
    for e in po.expenses.all():
        amt = q(e.amount_in_bzd(rate) if hasattr(e, "amount_in_bzd") else e.amount)
        if amt <= 0:
            continue
        cur = getattr(e, "currency", "BZD")
        label = f"{e.name}" + (f" ({e.amount} {cur} @ {rate})" if cur == "USD" else "")
        lines.append((inv_asset, amt, Z, label, None, po.supplier))
        total += amt
    if total <= 0:
        return None
    lines.append((accrued, Z, total, f"Landed-cost expenses — {po.po_no}", None, None))
    return _entry(timezone.localdate(), f"Landed-cost expenses — {po.po_no}",
                  JournalSource.BILL, po.id, user, lines, reference=f"{po.po_no}-EXP")


@transaction.atomic
def void_po_expenses(po, user=None):
    """Reverse a PO's landed-cost expense entry (used when deleting the PO)."""
    for je in list(_po_expense_entries(po)):
        _void_entry(je)


@transaction.atomic
def write_off_inventory(product, qty, unit_cost=None, user=None, reference=""):
    """Damage / shrinkage: Dr Inventory Shrinkage ; Cr Inventory Asset."""
    ensure_chart()
    cost = q(unit_cost if unit_cost is not None else getattr(product, "cost_price", 0))
    value = q(abs(Decimal(str(qty or 0))) * cost)
    if value <= 0:
        return None
    shrink = acc(CODES["SHRINK"])
    inv_asset = acc(CODES["INVENTORY"])
    if not (shrink and inv_asset):
        return None
    lines = [
        (shrink, value, Z, f"Write-off {product.sku} {reference}".strip(), None, None),
        (inv_asset, Z, value, f"Write-off {product.sku} {reference}".strip(), None, None),
    ]
    return _entry(timezone.localdate(), f"Inventory write-off — {product.sku}",
                  JournalSource.MANUAL, None, user, lines, reference=reference)


def auto_invoice_on_delivery(order, user=None):
    """When an order is delivered, generate & post its invoice if not already done.
    Books the sale (A/R, Sales, Tax) and the cost side (COGS, Inventory)."""
    try:
        if getattr(order, "invoice", None):
            return order.invoice
        if not Account.objects.exists():       # accounting not set up yet — skip
            return None
        return invoice_from_order(order, user=user, post=True)
    except Exception:
        return None