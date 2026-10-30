from django.urls import path
from . import views

urlpatterns = [
    # Customers
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/delete/", views.customer_delete, name="customer_delete"),
    path("api/customers/", views.customer_search_api, name="customer_search_api"),
    path("api/pricing/", views.pricing_api, name="pricing_api"),
    path("api/product/<int:pk>/", views.product_info_api, name="product_info_api"),

    # Orders
    path("", views.order_list, name="order_list"),
    path("new/", views.order_create, name="order_create"),
    path("<int:pk>/", views.order_detail, name="order_detail"),
    path("<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("<int:pk>/quotation/", views.order_quotation, name="order_quotation"),
    path("<int:pk>/invoice/", views.order_invoice, name="order_invoice"),
    path("<int:pk>/invoice.pdf", views.order_invoice_pdf, name="order_invoice_pdf"),
    path("<int:pk>/dispatch-note/", views.order_dispatch_note, name="order_dispatch_note"),
    path("<int:pk>/line-update/", views.order_line_update, name="order_line_update"),
    path("<int:pk>/line-add/", views.order_line_add, name="order_line_add"),
    path("<int:pk>/line-remove/", views.order_line_remove, name="order_line_remove"),
    path("<int:pk>/cancel/", views.order_cancel, name="order_cancel"),

    # Team lead
    path("review/", views.review_queue, name="review_queue"),
    path("<int:pk>/review/", views.order_review_action, name="order_review_action"),

    # Processing
    path("processing/", views.processing_queue, name="processing_queue"),
    path("<int:pk>/processing/", views.processing_action, name="processing_action"),
]