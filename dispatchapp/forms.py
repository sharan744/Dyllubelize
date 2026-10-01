from django import forms
from .models import Dispatch


class DispatchForm(forms.ModelForm):
    class Meta:
        model = Dispatch
        fields = ("vehicle_details", "driver_name", "driver_contact",
                  "dispatch_date", "expected_delivery_date",
                  "special_instructions", "remarks")
        widgets = {
            "dispatch_date": forms.DateInput(attrs={"type": "date"}),
            "expected_delivery_date": forms.DateInput(attrs={"type": "date"}),
            "special_instructions": forms.Textarea(attrs={"rows": 2}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }
