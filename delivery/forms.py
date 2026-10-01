from django import forms
from .models import DeliveryConfirmation


class DeliveryConfirmationForm(forms.ModelForm):
    class Meta:
        model = DeliveryConfirmation
        fields = ("delivered_at", "received_by", "signature_name",
                  "remarks", "pod_file")
        widgets = {
            "delivered_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["delivered_at"].input_formats = ["%Y-%m-%dT%H:%M"]
