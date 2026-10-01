from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import Role
from core.permissions import role_required
from orders.models import Order, OrderStatus
from .models import Return, ReturnLine, ReturnPhoto

# Warehouse-facing roles (admin always allowed)
RETURN_ROLES = (Role.DISPATCH, Role.DELIVERY)


def _dec(value):
    try:
        d = Decimal(str(value or "0"))
        return d if d > 0 else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


@role_required(*RETURN_ROLES)
def return_list(request):
    returns = Return.objects.select_related("order__customer").prefetch_related("lines")
    return render(request, "returnsapp/return_list.html", {"returns": returns})


@role_required(*RETURN_ROLES)
def return_create(request):
    order_id = request.GET.get("order")

    # Step 1 — choose the order the goods came back from
    if not order_id:
        eligible = (Order.objects
                    .filter(status__in=[OrderStatus.DISPATCHED, OrderStatus.DELIVERED,
                                        OrderStatus.COMPLETED])
                    .select_related("customer").order_by("-created_at"))
        return render(request, "returnsapp/return_choose.html", {"orders": eligible})

    order = get_object_or_404(Order.objects.select_related("customer"), pk=order_id)

    if request.method == "POST":
        ret = Return.objects.create(
            order=order,
            reason=request.POST.get("reason", Return.Reason.DAMAGED),
            reason_note=request.POST.get("reason_note", "")[:255],
            notes=request.POST.get("notes", ""),
            created_by=request.user,
        )
        any_line = False
        for it in order.items.select_related("product"):
            good = _dec(request.POST.get(f"good_{it.id}"))
            damaged = _dec(request.POST.get(f"damaged_{it.id}"))
            # never accept more than was ordered on that line
            cap = it.quantity
            if good + damaged > cap:
                # trim damaged first, then good, to fit the cap
                overflow = good + damaged - cap
                damaged = max(Decimal("0"), damaged - overflow)
                overflow = good + damaged - cap
                good = max(Decimal("0"), good - overflow)
            if good + damaged > 0:
                ReturnLine.objects.create(
                    ret=ret, product=it.product, product_name=it.product_name,
                    sku=it.sku, unit=it.unit, unit_price=it.unit_price,
                    good_qty=good, damaged_qty=damaged,
                    note=request.POST.get(f"note_{it.id}", "")[:255],
                )
                any_line = True

        if not any_line:
            ret.delete()
            messages.error(request, "Enter a good or damaged quantity for at least one item.")
            return redirect(f"/returns/new/?order={order.pk}")

        for f in request.FILES.getlist("photos"):
            ReturnPhoto.objects.create(ret=ret, image=f)

        messages.success(request, f"{ret.rma_no} created. Review it, then process to update stock.")
        return redirect("return_detail", pk=ret.pk)

    return render(request, "returnsapp/return_form.html", {"order": order})


@role_required(*RETURN_ROLES)
def return_detail(request, pk):
    ret = get_object_or_404(
        Return.objects.select_related("order__customer", "created_by", "processed_by")
        .prefetch_related("lines", "photos"), pk=pk
    )
    return render(request, "returnsapp/return_detail.html", {"ret": ret})


@role_required(*RETURN_ROLES)
def return_process(request, pk):
    ret = get_object_or_404(Return, pk=pk)
    if request.method == "POST" and ret.status == Return.Status.OPEN:
        ret.process(user=request.user)
        messages.success(request, f"{ret.rma_no} processed — good units restocked, "
                                  f"damaged units written off.")
    return redirect("return_detail", pk=pk)
