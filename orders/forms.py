from django import forms
from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ("name", "company_name", "contact_person", "mobile", "email",
                  "billing_address", "delivery_address", "tax_id", "notes")
        widgets = {
            "billing_address": forms.Textarea(attrs={"rows": 2}),
            "delivery_address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }
