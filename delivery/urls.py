from django.urls import path
from . import views

urlpatterns = [
    path("", views.delivery_queue, name="delivery_queue"),
    path("<int:pk>/confirm/", views.delivery_confirm, name="delivery_confirm"),
]
