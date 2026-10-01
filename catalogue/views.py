from django.contrib import messages
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404

from core.permissions import role_required, RoleRequiredMixin, ALL_STAFF
from .forms import CategoryForm, ProductForm
from .models import Category, Product, ProductSpec, COMMON_SPECS


def _save_specs(request, product):
    """Rebuild a product's specification rows from the submitted form arrays."""
    labels = request.POST.getlist("spec_label")
    values = request.POST.getlist("spec_value")
    product.specs.all().delete()
    pos = 0
    for i, label in enumerate(labels):
        label = (label or "").strip()
        value = (values[i] if i < len(values) else "").strip()
        if not label or not value:
            continue
        ProductSpec.objects.create(product=product, label=label[:80],
                                   value=value[:200], position=pos)
        pos += 1


@role_required(*ALL_STAFF)
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("specs"), pk=pk)
    return render(request, "catalogue/product_detail.html", {
        "product": product,
        "similar": product.similar_products(),
    })


@role_required(*ALL_STAFF)
def catalogue_browse(request):
    """Read-only catalogue for everyone; management links appear for admins."""
    q = request.GET.get("q", "").strip()
    cat = request.GET.get("category", "")
    products = Product.objects.filter(is_active=True).select_related("category")
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if cat:
        products = products.filter(category__slug=cat)
    categories = Category.objects.filter(is_active=True)
    return render(request, "catalogue/browse.html", {
        "products": products, "categories": categories,
        "q": q, "active_cat": cat,
    })


# ---------------- Category management (admin) ----------------
@role_required()
def category_list(request):
    categories = Category.objects.all()
    return render(request, "catalogue/category_list.html", {"categories": categories})


@role_required()
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category added.")
        return redirect("category_list")
    return render(request, "catalogue/category_form.html", {"form": form, "title": "Add Category"})


@role_required()
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category updated.")
        return redirect("category_list")
    return render(request, "catalogue/category_form.html",
                  {"form": form, "title": f"Edit {category.name}"})


@role_required()
def category_toggle(request, pk):
    category = get_object_or_404(Category, pk=pk)
    category.is_active = not category.is_active
    category.save()
    messages.info(request, f"Category “{category.name}” "
                           f"{'activated' if category.is_active else 'deactivated'}.")
    return redirect("category_list")


# ---------------- Product management (admin) ----------------
@role_required()
def product_list(request):
    q = request.GET.get("q", "").strip()
    products = Product.objects.select_related("category").all()
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    return render(request, "catalogue/product_list.html", {"products": products, "q": q})


@role_required()
def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        _save_specs(request, product)
        messages.success(request, "Product added.")
        return redirect("product_list")
    return render(request, "catalogue/product_form.html", {
        "form": form, "title": "Add Product",
        "common_specs": COMMON_SPECS, "specs": []})


@role_required()
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    if request.method == "POST" and form.is_valid():
        form.save()
        _save_specs(request, product)
        messages.success(request, "Product updated.")
        return redirect("product_list")
    return render(request, "catalogue/product_form.html", {
        "form": form, "title": f"Edit {product.name}",
        "common_specs": COMMON_SPECS,
        "specs": [{"label": s.label, "value": s.value} for s in product.specs.all()]})


@role_required()
def product_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save()
    messages.info(request, f"Product “{product.name}” "
                           f"{'activated' if product.is_active else 'deactivated'}.")
    return redirect("product_list")
