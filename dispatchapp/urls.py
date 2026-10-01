from django.urls import path
from . import views

urlpatterns = [
    path("", views.dispatch_list, name="dispatch_list"),
    path("new/", views.dispatch_create, name="dispatch_create"),
    path("<int:pk>/", views.dispatch_detail, name="dispatch_detail"),
    path("<int:pk>/send/", views.dispatch_mark_sent, name="dispatch_mark_sent"),
    path("<int:pk>/document/", views.delivery_document, name="delivery_document"),
]
