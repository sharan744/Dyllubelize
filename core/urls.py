from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("accounting/", views.accounting, name="accounting"),
    path("reports/", views.reports, name="reports"),
    path("incentives/", views.incentives, name="incentives"),
    path("reports/export/<str:kind>.csv", views.report_export, name="report_export"),
]
