from django.urls import path
from . import views

urlpatterns = [
    path("", views.return_list, name="return_list"),
    path("new/", views.return_create, name="return_create"),
    path("<int:pk>/", views.return_detail, name="return_detail"),
    path("<int:pk>/edit/", views.return_edit, name="return_edit"),
    path("<int:pk>/process/", views.return_process, name="return_process"),
    path("<int:pk>/credit-note/", views.return_credit_note, name="return_credit_note"),
    path("<int:pk>/credit-note.pdf", views.return_credit_note_pdf, name="return_credit_note_pdf"),
]