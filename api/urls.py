from django.urls import path
from . import views

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
]
