"""
Double-entry accounting for UDL Belize.

The general ledger is the single source of truth: every financial document
(invoice, customer payment, credit note, vendor bill, bill payment, manual
entry) posts a *balanced* JournalEntry. Reports (Trial Balance, P&L, Balance
Sheet, AR/AP aging) are all derived from the posted journal, exactly like
QuickBooks.
"""
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone

TWO = Decimal("0.01")
Z = Decimal("0.00")


def q(x):
    return (Decimal(str(x or 0))).quantize(TWO)


# ============================================================
# Chart of Accounts
# ============================================================
class AccountType(models.TextChoices):
    ASSET = "asset", "Asset"
    LIABILITY = "liability", "Liability"
    EQUITY = "equity", "Equity"
    INCOME = "income", "Income"
    EXPENSE = "expense", "Expense"


# Which side increases each type (debit-normal vs credit-normal)
DEBIT_NORMAL = {AccountType.ASSET, AccountType.EXPENSE}


class Account(models.Model):
    code = models.CharField(max_length=12, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=12, choices=AccountType.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    is_bank = models.BooleanField(
        default=False, help_text="Cash / bank account — appears in deposits & reconciliation.")
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def is_debit_normal(self):
        return self.type in DEBIT_NORMAL

    def ledger_lines(self, start=None, end=None):
        qs = JournalLine.objects.filter(account=self, entry__posted=True)
        if start:
            qs = qs.filter(entry__date__gte=start)
        if end:
            qs = qs.filter(entry__date__lte=end)
        return qs.select_related("entry")

    def balance(self, start=None, end=None):
        """Signed balance in the account's *natural* direction (positive = normal)."""
        agg = self.ledger_lines(start=start, end=end).aggregate(
            d=models.Sum("debit"), c=models.Sum("credit"))
        debit = agg["d"] or Z
        credit = agg["c"] or Z
        opening = self.opening_balance if not start else Z
        raw = (debit - credit) if self.is_debit_normal else (credit - debit)
        return q(raw + opening)


# ============================================================
# General Journal (double entry)
# ============================================================
class JournalSource(models.TextChoices):
    MANUAL = "manual", "Manual entry"
    INVOICE = "invoice", "Customer invoice"
    PAYMENT = "payment", "Customer payment"
    CREDIT = "credit", "Credit note"
    BILL = "bill", "Vendor bill"
    BILLPAY = "billpay", "Vendor payment"
    OPENING = "opening", "Opening balance"


class JournalEntry(models.Model):
    entry_no = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    date = models.DateField(default=timezone.localdate)
    memo = models.CharField(max_length=240, blank=True)
    reference = models.CharField(max_length=60, blank=True)
    source = models.CharField(max_length=12, choices=JournalSource.choices,
                              default=JournalSource.MANUAL)
    source_id = models.PositiveIntegerField(null=True, blank=True)
    posted = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "Journal entries"

    def __str__(self):
        return f"{self.entry_no} · {self.date}"

    def save(self, *args, **kwargs):
        if not self.entry_no:
            self.entry_no = self._next_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_no():
        prefix = "JE-"
        last = (JournalEntry.objects.filter(entry_no__startswith=prefix)
                .order_by("-id").first())
        n = 1
        if last:
            try:
                n = int(last.entry_no.split("-")[-1]) + 1
            except ValueError:
                n = JournalEntry.objects.count() + 1
        return f"{prefix}{n:06d}"

    @property
    def total_debit(self):
        return q(sum((l.debit for l in self.lines.all()), Z))

    @property
    def total_credit(self):
        return q(sum((l.credit for l in self.lines.all()), Z))

    @property
    def is_balanced(self):
        return self.total_debit == self.total_credit


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    memo = models.CharField(max_length=200, blank=True)
    # sub-ledger links (for AR/AP drill-down)
    customer = models.ForeignKey("orders.Customer", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="journal_lines")
    supplier = models.ForeignKey("inventory.Supplier", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="journal_lines")
    # bank reconciliation
    reconciled = models.BooleanField(default=False)
    reconciled_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        side = f"Dr {self.debit}" if self.debit else f"Cr {self.credit}"
        return f"{self.account.code} {side}"


# ============================================================
# Accounts Receivable — Invoices
# ============================================================
class DocStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    OPEN = "open", "Open"
    PARTIAL = "partial", "Partially paid"
    PAID = "paid", "Paid"
    VOID = "void", "Void"


class Invoice(models.Model):
    number = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    customer = models.ForeignKey("orders.Customer", on_delete=models.PROTECT,
                                 related_name="invoices")
    order = models.OneToOneField("orders.Order", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="invoice")
    date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    terms_days = models.PositiveIntegerField(default=30)
    memo = models.CharField(max_length=240, blank=True)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=DocStatus.choices,
                              default=DocStatus.DRAFT)
    show_in_ui = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "If enabled, this invoice will be visible "
            "in the user-facing invoice UI."
        ),
    )
    journal = models.ForeignKey(JournalEntry, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._next_no()
        if not self.due_date:
            self.due_date = self.date + timezone.timedelta(days=self.terms_days)
        super().save(*args, **kwargs)

    @staticmethod
    def _next_no():
        prefix = "INV-"
        last = Invoice.objects.filter(number__startswith=prefix).order_by("-id").first()
        n = 1
        if last:
            try:
                n = int(last.number.split("-")[-1]) + 1
            except ValueError:
                n = Invoice.objects.count() + 1
        return f"{prefix}{n:05d}"

    @property
    def subtotal(self):
        return q(sum((l.amount for l in self.lines.all()), Z))

    @property
    def tax(self):
        return q(self.subtotal * (self.tax_percent or 0) / 100)

    @property
    def total(self):
        return q(self.subtotal + self.tax)

    @property
    def amount_paid(self):
        applied = sum((a.amount for a in self.payment_applications.all()), Z)
        credited = sum((c.amount for c in self.credit_applications.all()), Z)
        return q(applied + credited)

    @property
    def balance(self):
        return q(self.total - self.amount_paid)

    @property
    def is_overdue(self):
        return self.balance > 0 and self.due_date and self.due_date < timezone.localdate()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days

    def recalc_status(self, commit=True):
        if self.status in (DocStatus.DRAFT, DocStatus.VOID):
            return
        bal = self.balance
        if bal <= 0:
            self.status = DocStatus.PAID
        elif self.amount_paid > 0:
            self.status = DocStatus.PARTIAL
        else:
            self.status = DocStatus.OPEN
        if commit:
            self.save(update_fields=["status"])


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalogue.Product", null=True, blank=True,
                                on_delete=models.SET_NULL)
    income_account = models.ForeignKey(Account, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    @property
    def amount(self):
        return q(self.quantity * self.unit_price)


# ============================================================
# Customer payments (receipts)
# ============================================================
class PayMethod(models.TextChoices):
    CASH = "cash", "Cash"
    CHEQUE = "cheque", "Cheque"
    BANK = "bank", "Bank transfer"
    CARD = "card", "Card"


class Payment(models.Model):
    number = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    customer = models.ForeignKey("orders.Customer", on_delete=models.PROTECT,
                                 related_name="payments")
    date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=8, choices=PayMethod.choices, default=PayMethod.BANK)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deposit_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                        help_text="Bank / cash account the money went into.")
    reference = models.CharField(max_length=60, blank=True, help_text="Cheque no. / txn ref")
    memo = models.CharField(max_length=200, blank=True)
    journal = models.ForeignKey(JournalEntry, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._next_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_no():
        prefix = "RCPT-"
        last = Payment.objects.filter(number__startswith=prefix).order_by("-id").first()
        n = 1
        if last:
            try:
                n = int(last.number.split("-")[-1]) + 1
            except ValueError:
                n = Payment.objects.count() + 1
        return f"{prefix}{n:05d}"

    @property
    def applied(self):
        return q(sum((a.amount for a in self.applications.all()), Z))

    @property
    def unapplied(self):
        return q(self.amount - self.applied)


class PaymentApplication(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="applications")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE,
                                related_name="payment_applications")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)


# ============================================================
# Credit notes
# ============================================================
class CreditNote(models.Model):
    number = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    customer = models.ForeignKey("orders.Customer", on_delete=models.PROTECT,
                                 related_name="credit_notes")
    date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=DocStatus.choices,
                              default=DocStatus.OPEN)
    journal = models.ForeignKey(JournalEntry, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._next_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_no():
        prefix = "CN-"
        last = CreditNote.objects.filter(number__startswith=prefix).order_by("-id").first()
        n = 1
        if last:
            try:
                n = int(last.number.split("-")[-1]) + 1
            except ValueError:
                n = CreditNote.objects.count() + 1
        return f"{prefix}{n:05d}"

    @property
    def applied(self):
        return q(sum((a.amount for a in self.applications.all()), Z))

    @property
    def remaining(self):
        return q(self.amount - self.applied)


class CreditApplication(models.Model):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE,
                                    related_name="applications")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE,
                                related_name="credit_applications")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)


# ============================================================
# Accounts Payable — Vendor bills
# ============================================================
class Bill(models.Model):
    number = models.CharField(max_length=30, db_index=True,
                              help_text="Vendor's bill / invoice number.")
    supplier = models.ForeignKey("inventory.Supplier", on_delete=models.PROTECT,
                                 related_name="bills")
    purchase_order = models.ForeignKey("inventory.PurchaseOrder", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="bills")
    date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    terms_days = models.PositiveIntegerField(default=30)
    memo = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=10, choices=DocStatus.choices,
                              default=DocStatus.DRAFT)
    journal = models.ForeignKey(JournalEntry, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.supplier} · {self.number}"

    def save(self, *args, **kwargs):
        if not self.due_date:
            self.due_date = self.date + timezone.timedelta(days=self.terms_days)
        super().save(*args, **kwargs)

    @property
    def total(self):
        return q(sum((l.amount for l in self.lines.all()), Z))

    @property
    def amount_paid(self):
        return q(sum((a.amount for a in self.payment_applications.all()), Z))

    @property
    def balance(self):
        return q(self.total - self.amount_paid)

    @property
    def is_overdue(self):
        return self.balance > 0 and self.due_date and self.due_date < timezone.localdate()

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days

    def recalc_status(self, commit=True):
        if self.status in (DocStatus.DRAFT, DocStatus.VOID):
            return
        if self.balance <= 0:
            self.status = DocStatus.PAID
        elif self.amount_paid > 0:
            self.status = DocStatus.PARTIAL
        else:
            self.status = DocStatus.OPEN
        if commit:
            self.save(update_fields=["status"])


class BillLine(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                help_text="Expense / asset account being charged.")
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]


class BillPayment(models.Model):
    number = models.CharField(max_length=20, unique=True, editable=False, db_index=True)
    supplier = models.ForeignKey("inventory.Supplier", on_delete=models.PROTECT,
                                 related_name="bill_payments")
    date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=8, choices=PayMethod.choices, default=PayMethod.BANK)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    pay_from = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                 help_text="Bank / cash account the money came out of.")
    reference = models.CharField(max_length=60, blank=True, help_text="Cheque no. / txn ref")
    memo = models.CharField(max_length=200, blank=True)
    journal = models.ForeignKey(JournalEntry, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._next_no()
        super().save(*args, **kwargs)

    @staticmethod
    def _next_no():
        prefix = "PAY-"
        last = BillPayment.objects.filter(number__startswith=prefix).order_by("-id").first()
        n = 1
        if last:
            try:
                n = int(last.number.split("-")[-1]) + 1
            except ValueError:
                n = BillPayment.objects.count() + 1
        return f"{prefix}{n:05d}"

    @property
    def applied(self):
        return q(sum((a.amount for a in self.applications.all()), Z))


class BillPaymentApplication(models.Model):
    payment = models.ForeignKey(BillPayment, on_delete=models.CASCADE,
                                related_name="applications")
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE,
                             related_name="payment_applications")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)


# ============================================================
# Budgets
# ============================================================
class Budget(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="budgets")
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField(
        default=0, help_text="1–12 for a monthly budget, or 0 for a full-year budget.")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["account__code", "year", "month"]
        unique_together = ("account", "year", "month")

    def __str__(self):
        return f"{self.account.code} {self.year}-{self.month or 'FY'}"


# ============================================================
# Bank reconciliation
# ============================================================
class Reconciliation(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="reconciliations")
    statement_date = models.DateField(default=timezone.localdate)
    statement_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    closed = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-statement_date"]

    def __str__(self):
        return f"{self.account.code} @ {self.statement_date}"
