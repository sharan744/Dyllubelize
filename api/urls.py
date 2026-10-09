from django.urls import path
from . import views
from . import views2

urlpatterns = [
    # auth
    path("auth/login/", views.login, name="api_login"),
    path("auth/logout/", views.logout, name="api_logout"),
    path("me/", views.me, name="api_me"),
    path("dashboard/", views.dashboard, name="api_dashboard"),

    # catalogue
    path("categories/", views.categories, name="api_categories"),
    path("products/", views.products, name="api_products"),
    path("products/<int:pk>/", views.product_detail, name="api_product_detail"),

    # customers
    path("customers/", views.customers, name="api_customers"),
    path("customers/<int:pk>/", views.customer_detail, name="api_customer_detail"),

    # orders
    path("orders/", views.orders, name="api_orders"),
    path("orders/<int:pk>/", views.order_detail, name="api_order_detail"),
    path("orders/<int:pk>/action/", views.order_action, name="api_order_action"),

    # suppliers
    path("suppliers/", views2.suppliers, name="api_suppliers"),

    # purchase orders
    path("purchase-orders/", views2.purchase_orders, name="api_pos"),
    path("purchase-orders/<int:pk>/", views2.po_detail, name="api_po_detail"),
    path("purchase-orders/<int:pk>/receive/", views2.po_receive, name="api_po_receive"),

    # inventory / stock
    path("inventory/", views2.inventory_overview, name="api_inventory"),
    path("inventory/movements/", views2.stock_movements, name="api_stock_movements"),
    path("inventory/expiring/", views2.expiring_batches, name="api_expiring"),

    # returns
    path("returns/", views2.returns, name="api_returns"),
    path("returns/<int:pk>/", views2.return_detail, name="api_return_detail"),
    path("returns/<int:pk>/action/", views2.return_action, name="api_return_action"),

    # dispatches
    path("dispatches/", views2.dispatches, name="api_dispatches"),
    path("dispatches/<int:pk>/", views2.dispatch_detail, name="api_dispatch_detail"),

    # deliveries
    path("deliveries/", views2.deliveries, name="api_deliveries"),
    path("deliveries/<int:pk>/", views2.delivery_detail, name="api_delivery_detail"),

    # accounting
    path("accounting/summary/", views2.accounting_summary, name="api_acc_summary"),
    path("accounting/invoices/", views2.invoices, name="api_invoices"),
    path("accounting/invoices/<int:pk>/", views2.invoice_detail, name="api_invoice_detail"),
    path("accounting/bills/", views2.bills, name="api_bills"),
    path("accounting/bills/<int:pk>/", views2.bill_detail, name="api_bill_detail"),
    path("accounting/payments/", views2.payments, name="api_payments"),
    path("accounting/accounts/", views2.chart_of_accounts, name="api_accounts"),
    path("accounting/pnl/", views2.profit_loss, name="api_pnl"),
    path("accounting/balance-sheet/", views2.balance_sheet, name="api_balance_sheet"),
]