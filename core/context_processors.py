from .models import SiteSetting


def company_settings(request):
    try:
        settings_obj = SiteSetting.get()
    except Exception:
        settings_obj = None

    counts = {}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        try:
            from orders.models import Order, OrderStatus
            if user.is_team_lead or user.is_admin_role:
                counts["review"] = Order.objects.filter(
                    status__in=[OrderStatus.SUBMITTED, OrderStatus.TEAM_LEAD_REVIEW]
                ).count()
            if user.is_processing or user.is_admin_role:
                counts["processing"] = Order.objects.filter(
                    status=OrderStatus.CONFIRMED).count()
            if user.is_dispatch or user.is_admin_role:
                counts["dispatch"] = Order.objects.filter(
                    status=OrderStatus.READY).count()
            if user.is_delivery or user.is_admin_role:
                counts["delivery"] = Order.objects.filter(
                    status=OrderStatus.DISPATCHED).count()
            if user.is_processing or user.is_dispatch or user.is_admin_role:
                from django.db.models import F
                from catalogue.models import Product
                counts["low_stock"] = Product.objects.filter(
                    track_stock=True, reorder_point__gt=0,
                    stock_qty__lte=F("reorder_point")).count()
                import datetime
                from catalogue.models import StockBatch
                limit = datetime.date.today() + datetime.timedelta(days=14)
                counts["expiring"] = StockBatch.objects.filter(
                    qty_remaining__gt=0, expiry_date__isnull=False,
                    expiry_date__lte=limit).count()
        except Exception:
            pass

    return {"site": settings_obj, "nav_counts": counts}
