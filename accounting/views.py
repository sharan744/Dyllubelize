import csv
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from core.permissions import role_required
from orders.models import Customer, Order, OrderStatus
from inventory.models import Supplier
from core.models import SiteSetting

from .models import (
    Account, AccountType, DEBIT_NORMAL, JournalEntry, JournalLine, JournalSource,
    Invoice, InvoiceLine, Payment, PaymentApplication, CreditNote, CreditApplication,
    Bill, BillLine, BillPayment, BillPaymentApplication, Budget, Reconciliation,
    DocStatus, q,
)
from . import services
from .forms import (
    AccountForm, InvoiceForm, PaymentForm, CreditNoteForm, BillForm,
    BillPaymentForm, BudgetForm, ReconciliationForm,
)

Z = Decimal("0.00")
# Accounting is an admin-only area (role_required() with no roles => admin only)
admin_only = role_required()


def _sym():
    return SiteSetting.get().currency_symbol


def _parse_range(request):
    today = timezone.localdate()
    default_start = today.replace(month=1, day=1)
    try:
        start = datetime.date.fromisoformat(request.GET["from"])
    except (KeyError, ValueError):
        start = default_start
    try:
        end = datetime.date.fromisoformat(request.GET["to"])
    except (KeyError, ValueError):
        end = today
    return start, end


def _accounts_follow_invoice_visibility():
    """Return whether Accounts should temporarily follow Invoice.show_in_ui."""
    return bool(SiteSetting.get().accounts_follow_invoice_visibility)


def _invoice_visible_ids():
    """IDs of invoices selected by Admin for UI/Accounts visibility."""
    return Invoice.objects.filter(show_in_ui=True).values("id")


def _accounting_entry_queryset():
    """
    Posted journal entries used by Accounts.

    When the Site Setting is OFF, this is the complete ledger.
    When ON, invoice-originated entries are limited to selected invoices.
    Customer payments/credit notes are retained when they are linked to at
    least one selected invoice. Bills, bill payments, manual and opening
    entries remain normal accounting data.
    """
    qs = JournalEntry.objects.filter(posted=True)
    if not _accounts_follow_invoice_visibility():
        return qs

    visible = _invoice_visible_ids()
    visible_payment_ids = PaymentApplication.objects.filter(
        invoice_id__in=visible
    ).values("payment_id")
    visible_credit_ids = CreditApplication.objects.filter(
        invoice_id__in=visible
    ).values("credit_note_id")

    from django.db.models import Q
    return qs.filter(
        Q(source__in=[
            JournalSource.MANUAL,
            JournalSource.OPENING,
            JournalSource.BILL,
            JournalSource.BILLPAY,
        ])
        | Q(source=JournalSource.INVOICE, source_id__in=visible)
        | Q(source=JournalSource.PAYMENT, source_id__in=visible_payment_ids)
        | Q(source=JournalSource.CREDIT, source_id__in=visible_credit_ids)
    )


def _acct_totals(start, end):
    """{account_id: (debit_sum, credit_sum)} for the active Accounts view."""
    qs = (_accounting_entry_queryset()
          .filter(date__gte=start, date__lte=end)
          .values("lines__account")
          .annotate(d=Sum("lines__debit"), c=Sum("lines__credit")))
    return {r["lines__account"]: (r["d"] or Z, r["c"] or Z) for r in qs}


def _balances_asof(end):
    """{account_id: (debit, credit)} as of end date for the active Accounts view."""
    qs = (_accounting_entry_queryset()
          .filter(date__lte=end)
          .values("lines__account")
          .annotate(d=Sum("lines__debit"), c=Sum("lines__credit")))
    out = {}
    for r in qs:
        out[r["lines__account"]] = ((r["d"] or Z), (r["c"] or Z))
    return out


# ============================================================
# Dashboard
# ============================================================
@admin_only
def home(request):
    if not Account.objects.exists():
        services.ensure_chart()

    today = timezone.localdate()
    month_start = today.replace(day=1)

    # P&L this month
    tot = _acct_totals(month_start, today)
    income = expense = Z
    for a in Account.objects.all():
        d, c = tot.get(a.id, (Z, Z))
        if a.type == AccountType.INCOME:
            income += (c - d)
        elif a.type == AccountType.EXPENSE:
            expense += (d - c)
    net = income - expense

    # balances
    filtered_balances = _balances_asof(today) if _accounts_follow_invoice_visibility() else None

    def bal(code):
        a = Account.objects.filter(code=code).first()
        if not a:
            return Z
        if filtered_balances is None:
            return a.balance()
        d, c = filtered_balances.get(a.id, (Z, Z))
        raw = (d - c) if a.is_debit_normal else (c - d)
        return q(raw + a.opening_balance)

    if filtered_balances is None:
        cash = sum((a.balance() for a in Account.objects.filter(is_bank=True)), Z)
    else:
        cash = Z
        for a in Account.objects.filter(is_bank=True):
            d, c = filtered_balances.get(a.id, (Z, Z))
            raw = (d - c) if a.is_debit_normal else (c - d)
            cash += q(raw + a.opening_balance)
    ar = bal(services.CODES["AR"])
    ap = bal(services.CODES["AP"])

    # AR/AP open docs
    invoice_qs = Invoice.objects.exclude(
        status__in=[DocStatus.DRAFT, DocStatus.VOID]
    ).select_related("customer")
    if _accounts_follow_invoice_visibility():
        invoice_qs = invoice_qs.filter(show_in_ui=True)
    open_invoices = [i for i in invoice_qs if i.balance > 0]
    overdue_ar = sum((i.balance for i in open_invoices if i.is_overdue), Z)
    open_bills = [b for b in Bill.objects.exclude(
        status__in=[DocStatus.DRAFT, DocStatus.VOID]).select_related("supplier")
        if b.balance > 0]

    recent = _accounting_entry_queryset().prefetch_related("lines")[:8]

    ctx = {
        "sym": _sym(), "income": income, "expense": expense, "net": net,
        "cash": cash, "ar": ar, "ap": ap,
        "overdue_ar": overdue_ar,
        "open_inv_count": len(open_invoices), "open_bill_count": len(open_bills),
        "open_bill_total": sum((b.balance for b in open_bills), Z),
        "recent": recent, "month_label": today.strftime("%B %Y"),
        "needs_seed": not JournalEntry.objects.exists(),
    }
    return render(request, "accounting/home.html", ctx)


@admin_only
def setup(request):
    """One-click: build chart of accounts + generate invoices from delivered orders."""
    if request.method == "POST":
        services.ensure_chart()
        made = 0
        if request.POST.get("backfill"):
            orders = (Order.objects
                      .filter(status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED])
                      .prefetch_related("items"))
            for o in orders:
                if getattr(o, "invoice", None):
                    continue
                inv = services.invoice_from_order(o, user=request.user, post=True)
                d = o.completed_at or o.confirmed_at or o.created_at
                inv.date = timezone.localtime(d).date()
                inv.save(update_fields=["date"])
                services.post_invoice(inv, user=request.user)
                made += 1
        messages.success(request, f"Chart of accounts ready. {made} invoice(s) generated from orders.")
        return redirect("acc_home")
    return render(request, "accounting/setup.html", {"sym": _sym()})


# ============================================================
# Chart of accounts
# ============================================================
@admin_only
def coa(request):
    accounts = list(Account.objects.all())
    groups = []
    filtered_balances = _balances_asof(timezone.localdate()) if _accounts_follow_invoice_visibility() else None

    def coa_balance(a):
        if filtered_balances is None:
            return a.balance()
        d, c = filtered_balances.get(a.id, (Z, Z))
        raw = (d - c) if a.is_debit_normal else (c - d)
        return q(raw + a.opening_balance)

    for atype, label in AccountType.choices:
        rows = [a for a in accounts if a.type == atype]
        subtotal = sum((coa_balance(a) for a in rows), Z)
        groups.append({"label": label, "type": atype, "rows": [
            {"a": a, "bal": coa_balance(a)} for a in rows], "subtotal": subtotal})
    return render(request, "accounting/coa.html", {"groups": groups, "sym": _sym()})


@admin_only
def account_new(request):
    form = AccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Account added.")
        return redirect("acc_coa")
    return render(request, "accounting/account_form.html", {"form": form})


@admin_only
def account_ledger(request, pk):
    account = get_object_or_404(Account, pk=pk)
    start, end = _parse_range(request)
    lines = (JournalLine.objects.filter(
                account=account,
                entry__in=_accounting_entry_queryset(),
                entry__date__gte=start,
                entry__date__lte=end,
            )
            .select_related("entry", "customer", "supplier")
            .order_by("entry__date", "id"))
    running = account.opening_balance
    rows = []
    for l in lines:
        delta = (l.debit - l.credit) if account.is_debit_normal else (l.credit - l.debit)
        running += delta
        rows.append({"l": l, "running": q(running)})
    return render(request, "accounting/account_ledger.html", {
        "account": account, "rows": rows, "start": start, "end": end,
        "opening": account.opening_balance, "closing": q(running), "sym": _sym()})


# ============================================================
# Journal
# ============================================================
@admin_only
def journal(request):
    entries = _accounting_entry_queryset().prefetch_related("lines__account")[:200]
    return render(request, "accounting/journal.html", {"entries": entries, "sym": _sym()})


@admin_only
def journal_new(request):
    accounts = Account.objects.filter(is_active=True)
    if request.method == "POST":
        date = request.POST.get("date") or timezone.localdate().isoformat()
        memo = request.POST.get("memo", "")
        reference = request.POST.get("reference", "")
        acc_ids = request.POST.getlist("account")
        debits = request.POST.getlist("debit")
        credits = request.POST.getlist("credit")
        line_memos = request.POST.getlist("line_memo")
        rows = []
        td = tc = Z
        for i, aid in enumerate(acc_ids):
            if not aid:
                continue
            try:
                d = Decimal(debits[i] or "0")
                c = Decimal(credits[i] or "0")
            except (InvalidOperation, IndexError):
                d = c = Z
            if d == 0 and c == 0:
                continue
            rows.append((int(aid), d, c, line_memos[i] if i < len(line_memos) else ""))
            td += d
            tc += c
        if not rows:
            messages.error(request, "Add at least one line.")
        elif q(td) != q(tc):
            messages.error(request, f"Entry is not balanced — debits {td} vs credits {tc}.")
        else:
            je = JournalEntry.objects.create(
                date=date, memo=memo, reference=reference,
                source=JournalSource.MANUAL, created_by=request.user, posted=True)
            for aid, d, c, lm in rows:
                JournalLine.objects.create(entry=je, account_id=aid, debit=q(d),
                                           credit=q(c), memo=lm)
            messages.success(request, f"Journal entry {je.entry_no} posted.")
            return redirect("acc_journal")
    return render(request, "accounting/journal_form.html",
                  {"accounts": accounts, "sym": _sym()})


# ============================================================
# Invoices (A/R)
# ============================================================
@admin_only
def invoice_list(request):
    status = request.GET.get("status", "")
    qs = Invoice.objects.select_related("customer", "order").filter(show_in_ui=True)
    if status:
        qs = qs.filter(status=status)
    invoices = list(qs[:400])
    total_open = sum((i.balance for i in invoices if i.balance > 0), Z)
    return render(request, "accounting/invoice_list.html", {
        "invoices": invoices, "sym": _sym(), "status": status,
        "total_open": total_open, "statuses": DocStatus.choices})


@admin_only
def invoice_new(request):
    form = InvoiceForm(request.POST or None)
    products = None
    if request.method == "POST" and form.is_valid():
        inv = form.save(commit=False)
        inv.created_by = request.user
        inv.save()
        # lines
        descs = request.POST.getlist("desc")
        qtys = request.POST.getlist("qty")
        prices = request.POST.getlist("price")
        sales = services.acc(services.CODES["SALES"])
        for i, d in enumerate(descs):
            if not d.strip():
                continue
            try:
                qty = Decimal(qtys[i] or "1")
                pr = Decimal(prices[i] or "0")
            except (InvalidOperation, IndexError):
                continue
            InvoiceLine.objects.create(invoice=inv, description=d[:200],
                                       quantity=qty, unit_price=pr, income_account=sales)
        if inv.lines.exists():
            services.post_invoice(inv, user=request.user)
            messages.success(request, f"Invoice {inv.number} created and posted.")
            return redirect("acc_invoice_detail", pk=inv.pk)
        inv.delete()
        messages.error(request, "Add at least one line item.")
    return render(request, "accounting/invoice_form.html", {"form": form})


@admin_only
def invoice_detail(request, pk):
    inv = get_object_or_404(Invoice.objects.select_related("customer", "order"), pk=pk)
    return render(request, "accounting/invoice_detail.html", {"inv": inv, "sym": _sym()})


@admin_only
def invoice_void(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    if request.method == "POST":
        services.void_invoice(inv, user=request.user)
        messages.success(request, f"Invoice {inv.number} voided.")
    return redirect("acc_invoice_detail", pk=pk)


@admin_only
def ar_aging(request):
    invoices = [i for i in Invoice.objects.exclude(
        status__in=[DocStatus.DRAFT, DocStatus.VOID]).select_related("customer")
        if i.balance > 0]
    buckets = {"current": Z, "d30": Z, "d60": Z, "d90": Z, "d90p": Z}
    by_cust = {}
    for i in invoices:
        od = i.days_overdue
        if od <= 0:
            key = "current"
        elif od <= 30:
            key = "d30"
        elif od <= 60:
            key = "d60"
        elif od <= 90:
            key = "d90"
        else:
            key = "d90p"
        buckets[key] += i.balance
        c = by_cust.setdefault(i.customer_id, {
            "name": str(i.customer), "id": i.customer_id,
            "current": Z, "d30": Z, "d60": Z, "d90": Z, "d90p": Z, "total": Z})
        c[key] += i.balance
        c["total"] += i.balance
    rows = sorted(by_cust.values(), key=lambda x: x["total"], reverse=True)
    total = sum(buckets.values(), Z)
    return render(request, "accounting/ar_aging.html", {
        "rows": rows, "buckets": buckets, "total": total, "sym": _sym()})


@admin_only
def statement(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    start, end = _parse_range(request)
    invoices = Invoice.objects.filter(customer=customer).exclude(
        status=DocStatus.VOID).order_by("date")
    payments = Payment.objects.filter(customer=customer).order_by("date")
    credits = CreditNote.objects.filter(customer=customer).exclude(
        status=DocStatus.VOID).order_by("date")
    events = []
    for i in invoices:
        events.append({"date": i.date, "type": "Invoice", "ref": i.number,
                       "charge": i.total, "credit": Z})
    for p in payments:
        events.append({"date": p.date, "type": "Payment", "ref": p.number,
                       "charge": Z, "credit": p.amount})
    for cn in credits:
        events.append({"date": cn.date, "type": "Credit Note", "ref": cn.number,
                       "charge": Z, "credit": cn.amount})
    events.sort(key=lambda e: (e["date"], e["type"]))
    running = Z
    for e in events:
        running += e["charge"] - e["credit"]
        e["balance"] = q(running)
    balance = q(running)
    return render(request, "accounting/statement.html", {
        "customer": customer, "events": events, "balance": balance,
        "start": start, "end": end, "sym": _sym(), "today": timezone.localdate(),
        "site": SiteSetting.get()})


# ============================================================
# Customer payments
# ============================================================
@admin_only
def payment_new(request):
    initial = {}
    cust_id = request.GET.get("customer")
    if cust_id:
        initial["customer"] = cust_id
    form = PaymentForm(request.POST or None, initial=initial)
    # default deposit account
    if not request.POST:
        bank = Account.objects.filter(is_bank=True, is_active=True).first()
        if bank:
            form.fields["deposit_account"].initial = bank.id
    open_invoices = []
    if cust_id:
        open_invoices = [i for i in Invoice.objects.filter(
            customer_id=cust_id).exclude(status__in=[DocStatus.DRAFT, DocStatus.VOID])
            if i.balance > 0]
    if request.method == "POST" and form.is_valid():
        pay = form.save(commit=False)
        pay.created_by = request.user
        pay.save()
        # apply to invoices
        inv_ids = request.POST.getlist("apply_invoice")
        amounts = request.POST.getlist("apply_amount")
        for i, iid in enumerate(inv_ids):
            try:
                amt = Decimal(amounts[i] or "0")
            except (InvalidOperation, IndexError):
                amt = Z
            if amt > 0:
                PaymentApplication.objects.create(payment=pay, invoice_id=iid, amount=q(amt))
        services.post_payment(pay, user=request.user)
        messages.success(request, f"Payment {pay.number} recorded.")
        return redirect("acc_payment_list")
    return render(request, "accounting/payment_form.html", {
        "form": form, "open_invoices": open_invoices, "sym": _sym(),
        "customers": Customer.objects.all()})


@admin_only
def payment_list(request):
    payments = Payment.objects.select_related("customer", "deposit_account")[:300]
    total = sum((p.amount for p in payments), Z)
    return render(request, "accounting/payment_list.html",
                  {"payments": payments, "sym": _sym(), "total": total})


# ============================================================
# Credit notes
# ============================================================
@admin_only
def credit_list(request):
    notes = CreditNote.objects.select_related("customer")[:300]
    return render(request, "accounting/credit_list.html", {"notes": notes, "sym": _sym()})


@admin_only
def credit_new(request):
    cust_id = request.GET.get("customer")
    # keep the picked customer selected after the reload that loads open invoices
    form = CreditNoteForm(request.POST or None,
                          initial={"customer": cust_id} if cust_id else None)
    open_invoices = []
    if cust_id:
        open_invoices = [i for i in Invoice.objects.filter(
            customer_id=cust_id).exclude(status__in=[DocStatus.DRAFT, DocStatus.VOID])
            if i.balance > 0]
    if request.method == "POST" and form.is_valid():
        cn = form.save(commit=False)
        cn.created_by = request.user
        cn.save()
        # optional application to invoices
        inv_ids = request.POST.getlist("apply_invoice")
        amounts = request.POST.getlist("apply_amount")
        for i, iid in enumerate(inv_ids):
            try:
                amt = Decimal(amounts[i] or "0")
            except (InvalidOperation, IndexError):
                amt = Z
            if amt > 0:
                CreditApplication.objects.create(credit_note=cn, invoice_id=iid, amount=q(amt))
        services.post_credit_note(cn, user=request.user)
        messages.success(request, f"Credit note {cn.number} issued.")
        return redirect("acc_credit_list")
    return render(request, "accounting/credit_form.html",
                  {"form": form, "customers": Customer.objects.all(),
                   "open_invoices": open_invoices, "sym": _sym()})


# API: open invoices for a customer (used by payment/credit forms)
@admin_only
def api_open_invoices(request):
    cid = request.GET.get("customer")
    data = []
    if cid:
        for i in Invoice.objects.filter(customer_id=cid).exclude(
                status__in=[DocStatus.DRAFT, DocStatus.VOID]):
            if i.balance > 0:
                data.append({"id": i.id, "number": i.number,
                             "date": i.date.isoformat(), "balance": float(i.balance)})
    return JsonResponse({"invoices": data})


# ============================================================
# Bills (A/P)
# ============================================================
@admin_only
def bill_list(request):
    bills = list(Bill.objects.select_related("supplier")[:400])
    total_open = sum((b.balance for b in bills if b.balance > 0), Z)
    return render(request, "accounting/bill_list.html",
                  {"bills": bills, "sym": _sym(), "total_open": total_open})


@admin_only
def bill_new(request):
    form = BillForm(request.POST or None)
    expense_accounts = Account.objects.filter(
        type__in=[AccountType.EXPENSE, AccountType.ASSET], is_active=True)
    if request.method == "POST" and form.is_valid():
        bill = form.save(commit=False)
        bill.created_by = request.user
        bill.save()
        acc_ids = request.POST.getlist("account")
        descs = request.POST.getlist("desc")
        amounts = request.POST.getlist("amount")
        for i, aid in enumerate(acc_ids):
            if not aid:
                continue
            try:
                amt = Decimal(amounts[i] or "0")
            except (InvalidOperation, IndexError):
                continue
            if amt <= 0:
                continue
            BillLine.objects.create(bill=bill, account_id=aid,
                                    description=(descs[i] if i < len(descs) else "")[:200],
                                    amount=q(amt))
        if bill.lines.exists():
            services.post_bill(bill, user=request.user)
            messages.success(request, f"Bill from {bill.supplier} recorded.")
            return redirect("acc_bill_detail", pk=bill.pk)
        bill.delete()
        messages.error(request, "Add at least one line.")
    return render(request, "accounting/bill_form.html",
                  {"form": form, "accounts": expense_accounts, "sym": _sym()})


@admin_only
def bill_detail(request, pk):
    bill = get_object_or_404(Bill.objects.select_related("supplier"), pk=pk)
    return render(request, "accounting/bill_detail.html", {"bill": bill, "sym": _sym()})


@admin_only
def ap_aging(request):
    bills = [b for b in Bill.objects.exclude(
        status__in=[DocStatus.DRAFT, DocStatus.VOID]).select_related("supplier")
        if b.balance > 0]
    buckets = {"current": Z, "d30": Z, "d60": Z, "d90": Z, "d90p": Z}
    by_sup = {}
    for b in bills:
        od = b.days_overdue
        if od <= 0:
            key = "current"
        elif od <= 30:
            key = "d30"
        elif od <= 60:
            key = "d60"
        elif od <= 90:
            key = "d90"
        else:
            key = "d90p"
        buckets[key] += b.balance
        s = by_sup.setdefault(b.supplier_id, {
            "name": str(b.supplier), "id": b.supplier_id,
            "current": Z, "d30": Z, "d60": Z, "d90": Z, "d90p": Z, "total": Z})
        s[key] += b.balance
        s["total"] += b.balance
    rows = sorted(by_sup.values(), key=lambda x: x["total"], reverse=True)
    total = sum(buckets.values(), Z)
    return render(request, "accounting/ap_aging.html", {
        "rows": rows, "buckets": buckets, "total": total, "sym": _sym()})


@admin_only
def bill_payment_new(request):
    sup_id = request.GET.get("supplier")
    # keep the picked supplier selected after the reload that loads open bills
    initial = {"supplier": sup_id} if sup_id else {}
    if not request.POST:
        bank = Account.objects.filter(is_bank=True, is_active=True).first()
        if bank:
            initial["pay_from"] = bank.id
    form = BillPaymentForm(request.POST or None, initial=initial)
    open_bills = []
    if sup_id:
        open_bills = [b for b in Bill.objects.filter(supplier_id=sup_id).exclude(
            status__in=[DocStatus.DRAFT, DocStatus.VOID]) if b.balance > 0]
    if request.method == "POST" and form.is_valid():
        bp = form.save(commit=False)
        bp.created_by = request.user
        bp.save()
        bill_ids = request.POST.getlist("apply_bill")
        amounts = request.POST.getlist("apply_amount")
        for i, bid in enumerate(bill_ids):
            try:
                amt = Decimal(amounts[i] or "0")
            except (InvalidOperation, IndexError):
                amt = Z
            if amt > 0:
                BillPaymentApplication.objects.create(payment=bp, bill_id=bid, amount=q(amt))
        services.post_bill_payment(bp, user=request.user)
        messages.success(request, f"Payment {bp.number} to {bp.supplier} recorded.")
        return redirect("acc_bill_list")
    return render(request, "accounting/bill_payment_form.html", {
        "form": form, "open_bills": open_bills, "suppliers": Supplier.objects.all(),
        "sym": _sym()})


@admin_only
def api_open_bills(request):
    sid = request.GET.get("supplier")
    data = []
    if sid:
        for b in Bill.objects.filter(supplier_id=sid).exclude(
                status__in=[DocStatus.DRAFT, DocStatus.VOID]):
            if b.balance > 0:
                data.append({"id": b.id, "number": b.number,
                             "date": b.date.isoformat(), "balance": float(b.balance)})
    return JsonResponse({"bills": data})


# ============================================================
# Banking & reconciliation
# ============================================================
@admin_only
def banking(request):
    banks = Account.objects.filter(is_bank=True)
    rows = []
    bals = _balances_asof(timezone.localdate())
    for a in banks:
        d, c = bals.get(a.id, (Z, Z))
        raw = (d - c) if a.is_debit_normal else (c - d)
        rows.append({"a": a, "bal": q(raw + a.opening_balance)})
    recons = Reconciliation.objects.select_related("account")[:20]
    return render(request, "accounting/banking.html",
                  {"rows": rows, "recons": recons, "sym": _sym()})


@admin_only
def reconcile(request):
    form = ReconciliationForm(request.POST or None)
    account = None
    aid = request.GET.get("account")
    if aid:
        account = Account.objects.filter(pk=aid, is_bank=True).first()
    if request.method == "POST":
        # toggle reconciled flags
        if request.POST.get("save_marks") and account:
            marked = set(request.POST.getlist("line"))
            for l in JournalLine.objects.filter(account=account, entry__in=_accounting_entry_queryset()):
                should = str(l.id) in marked
                if l.reconciled != should:
                    l.reconciled = should
                    l.reconciled_on = timezone.localdate() if should else None
                    l.save(update_fields=["reconciled", "reconciled_on"])
            messages.success(request, "Reconciliation saved.")
            return redirect(f"{request.path}?account={account.id}")
    lines = []
    cleared = Z
    if account:
        for l in JournalLine.objects.filter(
                account=account, entry__in=_accounting_entry_queryset()
        ).select_related("entry").order_by("entry__date"):
            lines.append(l)
            if l.reconciled:
                cleared += (l.debit - l.credit)
    return render(request, "accounting/reconcile.html", {
        "form": form, "account": account, "lines": lines,
        "cleared": q(cleared + (account.opening_balance if account else Z)),
        "bank_accounts": Account.objects.filter(is_bank=True), "sym": _sym()})


# ============================================================
# Budgets
# ============================================================
@admin_only
def budgets(request):
    year = int(request.GET.get("year", timezone.localdate().year))
    form = BudgetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        b = form.save(commit=False)
        Budget.objects.update_or_create(
            account=b.account, year=b.year, month=b.month,
            defaults={"amount": b.amount})
        messages.success(request, "Budget saved.")
        return redirect(f"{request.path}?year={b.year}")

    start = datetime.date(year, 1, 1)
    end = datetime.date(year, 12, 31)
    tot = _acct_totals(start, end)
    rows = []
    for a in Account.objects.filter(type__in=[AccountType.INCOME, AccountType.EXPENSE],
                                    is_active=True):
        d, c = tot.get(a.id, (Z, Z))
        actual = (c - d) if a.type == AccountType.INCOME else (d - c)
        budget = sum((b.amount for b in a.budgets.filter(year=year)), Z)
        if actual == 0 and budget == 0:
            continue
        var = budget - actual if a.type == AccountType.EXPENSE else actual - budget
        rows.append({"a": a, "actual": q(actual), "budget": q(budget), "var": q(var)})
    return render(request, "accounting/budgets.html", {
        "rows": rows, "year": year, "form": form, "sym": _sym(),
        "years": range(timezone.localdate().year - 3, timezone.localdate().year + 2)})


# ============================================================
# Financial reports
# ============================================================
@admin_only
def report_pnl(request):
    start, end = _parse_range(request)
    tot = _acct_totals(start, end)
    income, expense = [], []
    tot_inc = tot_exp = Z
    for a in Account.objects.filter(type=AccountType.INCOME, is_active=True):
        d, c = tot.get(a.id, (Z, Z))
        val = q(c - d)
        if val:
            income.append({"a": a, "val": val})
            tot_inc += val
    for a in Account.objects.filter(type=AccountType.EXPENSE, is_active=True):
        d, c = tot.get(a.id, (Z, Z))
        val = q(d - c)
        if val:
            expense.append({"a": a, "val": val})
            tot_exp += val
    net = q(tot_inc - tot_exp)
    if request.GET.get("export") == "csv":
        return _csv_pnl(income, expense, tot_inc, tot_exp, net, start, end)
    return render(request, "accounting/report_pnl.html", {
        "income": income, "expense": expense, "tot_inc": tot_inc,
        "tot_exp": tot_exp, "net": net, "start": start, "end": end, "sym": _sym()})


def _csv_pnl(income, expense, tot_inc, tot_exp, net, start, end):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="pnl_{start}_{end}.csv"'
    w = csv.writer(resp)
    w.writerow(["Profit & Loss", f"{start} to {end}"])
    w.writerow([])
    w.writerow(["Income"])
    for r in income:
        w.writerow([r["a"].code, r["a"].name, r["val"]])
    w.writerow(["", "Total Income", tot_inc])
    w.writerow(["Expenses"])
    for r in expense:
        w.writerow([r["a"].code, r["a"].name, r["val"]])
    w.writerow(["", "Total Expenses", tot_exp])
    w.writerow(["", "Net Profit", net])
    return resp


@admin_only
def report_balance_sheet(request):
    _, end = _parse_range(request)
    bals = _balances_asof(end)

    def signed(a):
        d, c = bals.get(a.id, (Z, Z))
        raw = (d - c) if a.type in DEBIT_NORMAL else (c - d)
        return q(raw + a.opening_balance)

    assets, liabilities, equity = [], [], []
    ta = tl = te = Z
    for a in Account.objects.filter(type=AccountType.ASSET, is_active=True):
        v = signed(a)
        if v:
            assets.append({"a": a, "val": v}); ta += v
    for a in Account.objects.filter(type=AccountType.LIABILITY, is_active=True):
        v = signed(a)
        if v:
            liabilities.append({"a": a, "val": v}); tl += v
    for a in Account.objects.filter(type=AccountType.EQUITY, is_active=True):
        v = signed(a)
        if v:
            equity.append({"a": a, "val": v}); te += v

    # net income (all income - expense up to end) rolls into equity
    ni = Z
    for a in Account.objects.filter(type__in=[AccountType.INCOME, AccountType.EXPENSE]):
        d, c = bals.get(a.id, (Z, Z))
        if a.type == AccountType.INCOME:
            ni += (c - d)
        else:
            ni -= (d - c)
    ni = q(ni)
    te_with_ni = q(te + ni)
    return render(request, "accounting/report_bs.html", {
        "assets": assets, "liabilities": liabilities, "equity": equity,
        "ta": ta, "tl": tl, "te": te, "ni": ni, "te_total": te_with_ni,
        "liab_eq": q(tl + te_with_ni), "end": end, "sym": _sym()})


@admin_only
def report_trial_balance(request):
    start, end = _parse_range(request)
    bals = _balances_asof(end)
    rows = []
    td = tc = Z
    for a in Account.objects.filter(is_active=True):
        d, c = bals.get(a.id, (Z, Z))
        net = d - c + (a.opening_balance if a.is_debit_normal else -a.opening_balance)
        debit = q(net) if net > 0 else Z
        credit = q(-net) if net < 0 else Z
        if debit == 0 and credit == 0:
            continue
        rows.append({"a": a, "debit": debit, "credit": credit})
        td += debit
        tc += credit
    return render(request, "accounting/report_tb.html", {
        "rows": rows, "td": q(td), "tc": q(tc), "end": end, "sym": _sym()})


@admin_only
def report_sales(request):
    """Sales by salesperson / customer / product from posted invoices."""
    start, end = _parse_range(request)
    invoices = Invoice.objects.filter(
        date__gte=start, date__lte=end
    ).exclude(status=DocStatus.VOID).select_related("customer", "order__salesperson")
    if _accounts_follow_invoice_visibility():
        invoices = invoices.filter(show_in_ui=True)
    by_cust, by_person, by_product = {}, {}, {}
    grand = Z
    for inv in invoices:
        grand += inv.subtotal
        by_cust[str(inv.customer)] = by_cust.get(str(inv.customer), Z) + inv.subtotal
        sp = inv.order.salesperson if inv.order_id and inv.order.salesperson else None
        name = sp.display_name if sp else "—"
        by_person[name] = by_person.get(name, Z) + inv.subtotal
        for l in inv.lines.all():
            by_product[l.description] = by_product.get(l.description, Z) + l.amount

    def top(d):
        return sorted(({"name": k, "val": q(v)} for k, v in d.items()),
                      key=lambda x: x["val"], reverse=True)
    return render(request, "accounting/report_sales.html", {
        "by_cust": top(by_cust), "by_person": top(by_person),
        "by_product": top(by_product)[:25], "grand": q(grand),
        "start": start, "end": end, "sym": _sym()})