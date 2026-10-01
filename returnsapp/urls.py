from django.urls import path
from . import views

urlpatterns = [
    path("", views.return_list, name="return_list"),
    path("new/", views.return_create, name="return_create"),
    path("<int:pk>/", views.return_detail, name="return_detail"),
    path("<int:pk>/process/", views.return_process, name="return_process"),
]
