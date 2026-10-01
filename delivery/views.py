from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.models import Role
from core.permissions import role_required
from orders.models import Order, OrderStatus
from .forms import DeliveryConfirmationForm
from .models import DeliveryConfirmation


@role_required(Role.DELIVERY)
def delivery_queue(request):
    orders = Order.objects.filter(
        status=OrderStatus.DISPATCHED
    ).select_related("customer").prefetch_related("dispatches")
    done = Order.objects.filter(
        status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED]
    ).select_related("customer")[:20]
    return render(request, "delivery/delivery_queue.html", {
        "orders": orders, "done": done,
    })


@role_required(Role.DELIVERY)
def delivery_confirm(request, pk):
    order = get_object_or_404(Order, pk=pk)
    existing = getattr(order, "delivery", None)

    if request.method == "POST":
        form = DeliveryConfirmationForm(request.POST, request.FILES, instance=existing)
        if form.is_valid():
            confirmation = form.save(commit=False)
            confirmation.order = order
            confirmation.delivered_by = request.user
            confirmation.dispatch = order.dispatches.first()
            confirmation.save()
            order.set_status(OrderStatus.DELIVERED, user=request.user,
                             note="Delivered — POD captured")
            # auto-complete
            order.set_status(OrderStatus.COMPLETED, user=request.user,
                             note="Order completed")
            from core.notifications import notify_delivered
            notify_delivered(order)
            messages.success(request, f"Delivery confirmed for {order.order_no}.")
            return redirect("delivery_queue")
    else:
        initial = {}
        if not existing:
            initial["delivered_at"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
            initial["received_by"] = order.customer.contact_person or order.customer.name
        form = DeliveryConfirmationForm(instance=existing, initial=initial)

    return render(request, "delivery/delivery_confirm.html", {"order": order, "form": form})
