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
        # Show every category from the table (ordered), so the dropdown is never
        # empty just because a category was marked inactive.
        self.fields["category"].queryset = Category.objects.all().order_by("name")
