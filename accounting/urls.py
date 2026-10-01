from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="acc_home"),
    path("setup/", views.setup, name="acc_setup"),

    # Chart of accounts
    path("coa/", views.coa, name="acc_coa"),
    path("coa/new/", views.account_new, name="acc_account_new"),
    path("coa/<int:pk>/", views.account_ledger, name="acc_account_ledger"),

    # Journal
    path("journal/", views.journal, name="acc_journal"),
    path("journal/new/", views.journal_new, name="acc_journal_new"),

    # A/R
    path("invoices/", views.invoice_list, name="acc_invoice_list"),
    path("invoices/new/", views.invoice_new, name="acc_invoice_new"),
    path("invoices/<int:pk>/", views.invoice_detail, name="acc_invoice_detail"),
    path("invoices/<int:pk>/void/", views.invoice_void, name="acc_invoice_void"),
    path("ar-aging/", views.ar_aging, name="acc_ar_aging"),
    path("statement/<int:customer_id>/", views.statement, name="acc_statement"),
    path("payments/", views.payment_list, name="acc_payment_list"),
    path("payments/new/", views.payment_new, name="acc_payment_new"),
    path("credits/", views.credit_list, name="acc_credit_list"),
    path("credits/new/", views.credit_new, name="acc_credit_new"),
    path("api/open-invoices/", views.api_open_invoices, name="acc_api_open_invoices"),

    # A/P
    path("bills/", views.bill_list, name="acc_bill_list"),
    path("bills/new/", views.bill_new, name="acc_bill_new"),
    path("bills/<int:pk>/", views.bill_detail, name="acc_bill_detail"),
    path("ap-aging/", views.ap_aging, name="acc_ap_aging"),
    path("bills/pay/", views.bill_payment_new, name="acc_bill_payment_new"),
    path("api/open-bills/", views.api_open_bills, name="acc_api_open_bills"),

    # Banking
    path("banking/", views.banking, name="acc_banking"),
    path("reconcile/", views.reconcile, name="acc_reconcile"),

    # Budgets
    path("budgets/", views.budgets, name="acc_budgets"),

    # Reports
    path("reports/pnl/", views.report_pnl, name="acc_report_pnl"),
    path("reports/balance-sheet/", views.report_balance_sheet, name="acc_report_bs"),
    path("reports/trial-balance/", views.report_trial_balance, name="acc_report_tb"),
    path("reports/sales/", views.report_sales, name="acc_report_sales"),
]
