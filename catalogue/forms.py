from django import forms
from .models import Category, Product


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description", "is_active")
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ("name", "category", "sku", "brand", "image", "long_description",
                  "unit", "selling_price", "cost_price", "stock_qty", "reorder_point",
                  "track_stock", "is_perishable", "expiry_alert_days", "is_active")
        widgets = {"long_description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
