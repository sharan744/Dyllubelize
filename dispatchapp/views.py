from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from accounts.models import Role
from core.permissions import role_required, ALL_STAFF
from orders.models import Order, OrderStatus
from .forms import DispatchForm
from .models import Dispatch


@role_required(Role.DISPATCH)
def dispatch_list(request):
    dispatches = Dispatch.objects.prefetch_related("orders__customer").all()
    ready_count = Order.objects.filter(status=OrderStatus.READY).count()
    return render(request, "dispatchapp/dispatch_list.html", {
        "dispatches": dispatches, "ready_count": ready_count,
    })


@role_required(Role.DISPATCH)
def dispatch_create(request):
    ready_orders = Order.objects.filter(
        status=OrderStatus.READY
    ).select_related("customer")

    if request.method == "POST":
        form = DispatchForm(request.POST)
        order_ids = request.POST.getlist("orders")
        if not order_ids:
            messages.error(request, "Select at least one order to dispatch.")
        elif form.is_valid():
            dispatch = form.save(commit=False)
            dispatch.created_by = request.user
            dispatch.save()
            selected = Order.objects.filter(pk__in=order_ids, status=OrderStatus.READY)
            dispatch.orders.set(selected)
            messages.success(
                request,
                f"Dispatch {dispatch.dispatch_no} created with {selected.count()} order(s).",
            )
            return redirect("dispatch_detail", pk=dispatch.pk)
    else:
        form = DispatchForm()

    return render(request, "dispatchapp/dispatch_form.html", {
        "form": form, "ready_orders": ready_orders,
    })


@role_required(*ALL_STAFF)
def dispatch_detail(request, pk):
    dispatch = get_object_or_404(
        Dispatch.objects.prefetch_related("orders__items", "orders__customer"), pk=pk
    )
    return render(request, "dispatchapp/dispatch_detail.html", {"dispatch": dispatch})


@role_required(Role.DISPATCH)
def dispatch_mark_sent(request, pk):
    dispatch = get_object_or_404(Dispatch, pk=pk)
    if request.method == "POST":
        dispatch.status = Dispatch.Status.DISPATCHED
        dispatch.save()
        from core.notifications import notify_dispatched
        for order in dispatch.orders.all():
            if order.status == OrderStatus.READY:
                order.set_status(OrderStatus.DISPATCHED, user=request.user,
                                 note=f"Dispatched on {dispatch.dispatch_no}")
                notify_dispatched(order)
        messages.success(request, f"{dispatch.dispatch_no} marked as dispatched.")
    return redirect("dispatch_detail", pk=pk)


@role_required(*ALL_STAFF)
def delivery_document(request, pk):
    """Clean A4 printable delivery / dispatch document."""
    dispatch = get_object_or_404(
        Dispatch.objects.prefetch_related("orders__items", "orders__customer"), pk=pk
    )
    return render(request, "dispatchapp/delivery_document.html", {"dispatch": dispatch})
