"""UDL Belize mobile API — token auth, catalogue, customers, orders + pipeline."""
import json
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.models import Role
from catalogue.models import Category, Product, StockMovement
from orders.models import (
    Customer, Order, OrderItem, OrderStatus, STATUS_PIPELINE,
)
from .serializers import (
    UserSerializer, CategorySerializer, ProductSerializer, ProductDetailSerializer,
    CustomerSerializer, OrderListSerializer, OrderDetailSerializer,
)


# ------------------------------------------------------------------ auth
@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    from django.contrib.auth import authenticate
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    user = authenticate(username=username, password=password)
    if not user or not user.is_active:
        return Response({"detail": "Invalid username or password."},
                        status=http.HTTP_401_UNAUTHORIZED)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key,
                     "user": UserSerializer(user).data})


@api_view(["POST"])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response({"detail": "Logged out."})


@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


# ------------------------------------------------------------------ dashboard
@api_view(["GET"])
def dashboard(request):
    u = request.user
    data = {"user": UserSerializer(u).data, "cards": {}}
    c = data["cards"]
    if u.is_team_lead or u.is_admin_role:
        c["review"] = Order.objects.filter(
            status__in=[OrderStatus.SUBMITTED, OrderStatus.TEAM_LEAD_REVIEW]).count()
    if u.is_processing or u.is_admin_role:
        c["processing"] = Order.objects.filter(status=OrderStatus.CONFIRMED).count()
    if u.is_dispatch or u.is_admin_role:
        c["dispatch"] = Order.objects.filter(status=OrderStatus.READY).count()
    if u.is_delivery or u.is_admin_role:
        c["delivery"] = Order.objects.filter(status=OrderStatus.DISPATCHED).count()
    # my recent orders
    recent = Order.objects.select_related("customer", "salesperson")
    if u.is_sales and not u.is_admin_role:
        recent = recent.filter(salesperson=u)
    data["recent"] = OrderListSerializer(recent[:10], many=True,
                                         context={"request": request}).data
    data["total_orders"] = Order.objects.count()
    return Response(data)


# ------------------------------------------------------------------ catalogue
@api_view(["GET"])
def categories(request):
    return Response(CategorySerializer(
        Category.objects.filter(is_active=True), many=True).data)


@api_view(["GET"])
def products(request):
    qs = Product.objects.filter(is_active=True).select_related("category")
    q = request.GET.get("q", "").strip()
    cat = request.GET.get("category", "")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    if cat:
        qs = qs.filter(category_id=cat)
    return Response(ProductSerializer(qs, many=True,
                                      context={"request": request}).data)


@api_view(["GET"])
def product_detail(request, pk):
    p = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("specs"), pk=pk)
    return Response(ProductDetailSerializer(p, context={"request": request}).data)


# ------------------------------------------------------------------ customers
@api_view(["GET", "POST"])
def customers(request):
    if request.method == "POST":
        ser = CustomerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        obj = ser.save(created_by=request.user)
        return Response(CustomerSerializer(obj).data, status=http.HTTP_201_CREATED)
    qs = Customer.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(company_name__icontains=q)
                       | Q(mobile__icontains=q))
    return Response(CustomerSerializer(qs[:100], many=True).data)


@api_view(["GET"])
def customer_detail(request, pk):
    return Response(CustomerSerializer(get_object_or_404(Customer, pk=pk)).data)


# ------------------------------------------------------------------ orders
def _dec(v, default="0"):
    try:
        return Decimal(str(v if v not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


@api_view(["GET", "POST"])
def orders(request):
    if request.method == "POST":
        return _create_order(request)
    u = request.user
    qs = Order.objects.select_related("customer", "salesperson")
    # role scoping
    if u.is_sales and not u.is_admin_role:
        qs = qs.filter(salesperson=u)
    st = request.GET.get("status", "")
    if st:
        qs = qs.filter(status=st)
    return Response(OrderListSerializer(qs[:200], many=True,
                                        context={"request": request}).data)


@api_view(["GET"])
def order_detail(request, pk):
    o = get_object_or_404(Order.objects.select_related("customer", "salesperson"), pk=pk)
    return Response(OrderDetailSerializer(o, context={"request": request}).data)


def _create_order(request):
    u = request.user
    if not (u.is_sales or u.is_admin_role):
        return Response({"detail": "Only sales can create orders."},
                        status=http.HTTP_403_FORBIDDEN)
    customer_id = request.data.get("customer")
    if not customer_id:
        return Response({"detail": "customer is required."}, status=http.HTTP_400_BAD_REQUEST)
    customer = get_object_or_404(Customer, pk=customer_id)
    items = request.data.get("items") or []
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            items = []
    if not items:
        return Response({"detail": "Add at least one item."}, status=http.HTTP_400_BAD_REQUEST)

    action = request.data.get("action", "draft")
    order = Order(customer=customer, salesperson=u)
    order.remarks = request.data.get("remarks", "") or ""
    order.discount_percent = _dec(request.data.get("discount_percent"))
    order.save()
    for it in items:
        try:
            product = Product.objects.get(pk=it.get("id") or it.get("product"))
        except (Product.DoesNotExist, ValueError, TypeError):
            continue
        OrderItem.objects.create(
            order=order, product=product, product_name=product.name,
            sku=product.sku, unit=product.get_unit_display(),
            unit_price=_dec(it.get("price", product.selling_price)),
            quantity=_dec(it.get("qty", 1) or 1),
            line_discount_percent=_dec(it.get("discount", 0)),
            note=str(it.get("note", ""))[:255])
    if not order.items.exists():
        order.delete()
        return Response({"detail": "No valid items."}, status=http.HTTP_400_BAD_REQUEST)

    if action == "submit":
        order.set_status(OrderStatus.SUBMITTED, user=u, note="Submitted from mobile")
        try:
            from core.notifications import notify_new_order
            notify_new_order(order)
        except Exception:
            pass
    return Response(OrderDetailSerializer(order, context={"request": request}).data,
                    status=http.HTTP_201_CREATED)


# Which role may move an order to which status (mobile pipeline)
_ACTIONS = {
    "submit":   (OrderStatus.SUBMITTED,  (Role.SALES,)),
    "approve":  (OrderStatus.CONFIRMED,  (Role.TEAM_LEAD,)),
    "reject":   (OrderStatus.REJECTED,   (Role.TEAM_LEAD,)),
    "process":  (OrderStatus.PROCESSING, (Role.PROCESSING,)),
    "ready":    (OrderStatus.READY,      (Role.PROCESSING,)),
    "dispatch": (OrderStatus.DISPATCHED, (Role.DISPATCH,)),
    "deliver":  (OrderStatus.DELIVERED,  (Role.DELIVERY,)),
    "complete": (OrderStatus.COMPLETED,  (Role.DELIVERY, Role.TEAM_LEAD)),
    "cancel":   (OrderStatus.CANCELLED,  (Role.SALES, Role.TEAM_LEAD)),
}


@api_view(["POST"])
def order_action(request, pk):
    o = get_object_or_404(Order, pk=pk)
    u = request.user
    action = request.data.get("action", "")
    if action not in _ACTIONS:
        return Response({"detail": f"Unknown action '{action}'."}, status=http.HTTP_400_BAD_REQUEST)
    new_status, roles = _ACTIONS[action]
    if not (u.is_admin_role or u.role in roles):
        return Response({"detail": "You don't have permission for this action."},
                        status=http.HTTP_403_FORBIDDEN)
    note = request.data.get("note", "") or f"{action} from mobile"
    o.set_status(new_status, user=u, note=note)
    if action == "approve":
        o.team_lead_remarks = request.data.get("note", "") or o.team_lead_remarks
        o.save(update_fields=["team_lead_remarks"])
    # fire customer notifications on dispatch / delivery (best-effort)
    try:
        from core import notifications
        if action == "dispatch":
            notifications.notify_dispatched(o)
        elif action == "deliver":
            notifications.notify_delivered(o)
    except Exception:
        pass
    return Response(OrderDetailSerializer(o, context={"request": request}).data)
