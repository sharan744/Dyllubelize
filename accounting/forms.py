from django import forms
from .models import (
    Account, AccountType, Invoice, Payment, CreditNote, Bill, BillPayment,
    Budget, PayMethod, Reconciliation,
)


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ("code", "name", "type", "parent", "is_bank", "is_active", "description")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["parent"].queryset = Account.objects.filter(is_active=True)
        self.fields["parent"].required = False


class JournalEntryHeaderForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    memo = forms.CharField(max_length=240, required=False)
    reference = forms.CharField(max_length=60, required=False)


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ("customer", "date", "terms_days", "tax_percent", "memo")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ("customer", "date", "method", "amount", "deposit_account",
                  "reference", "memo")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["deposit_account"].queryset = Account.objects.filter(
            is_bank=True, is_active=True)


class CreditNoteForm(forms.ModelForm):
    class Meta:
        model = CreditNote
        fields = ("customer", "date", "amount", "reason")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class BillForm(forms.ModelForm):
    class Meta:
        model = Bill
        fields = ("supplier", "number", "date", "terms_days", "memo")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class BillPaymentForm(forms.ModelForm):
    class Meta:
        model = BillPayment
        fields = ("supplier", "date", "method", "amount", "pay_from", "reference", "memo")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["pay_from"].queryset = Account.objects.filter(
            is_bank=True, is_active=True)


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ("account", "year", "month", "amount")

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["account"].queryset = Account.objects.filter(
            type__in=[AccountType.INCOME, AccountType.EXPENSE], is_active=True)


class ReconciliationForm(forms.ModelForm):
    class Meta:
        model = Reconciliation
        fields = ("account", "statement_date", "statement_balance")
        widgets = {"statement_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.fields["account"].queryset = Account.objects.filter(
            is_bank=True, is_active=True)
