from django.urls import path
from . import views

urlpatterns = [
    path("", views.inventory_overview, name="inventory_overview"),
    path("adjust/", views.stock_adjust, name="stock_adjust"),
    path("expiring/", views.expiring_soon, name="expiring_soon"),
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path("suppliers/<int:pk>/edit/", views.supplier_edit, name="supplier_edit"),
    path("po/", views.po_list, name="po_list"),
    path("po/new/", views.po_create, name="po_create"),
    path("po/<int:pk>/", views.po_detail, name="po_detail"),
    path("po/<int:pk>/action/", views.po_action, name="po_action"),
]
