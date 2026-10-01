"""
Demo seeder for the perishable / expiry feature.

Marks a handful of existing products as perishable and gives each a few dated
batches — one already expired, one due in a couple of days, one comfortably
ahead — so the "Expiring Soon" page and the alert email are populated right away.

    python manage.py seed_expiry               # perishable-ise ~5 products
    python manage.py seed_expiry --count 8     # more products
    python manage.py seed_expiry --reset        # clear existing demo batches first

Then, to see the alert email in your terminal:
    (Windows CMD)   set USE_CONSOLE_EMAIL=True && python manage.py check_expiry
    (PowerShell)    $env:USE_CONSOLE_EMAIL="True"; python manage.py check_expiry
    (mac/Linux)     USE_CONSOLE_EMAIL=True python manage.py check_expiry
"""
import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Seed perishable products with near-expiry batches for a quick demo."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=5,
                            help="How many products to make perishable (default 5).")
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing batches on those products first.")

    def handle(self, *args, **opts):
        from catalogue.models import Product, StockBatch, StockMovement

        today = timezone.localdate()
        # prefer fruit/veg-type categories, else just the first stock-tracked products
        qs = Product.objects.filter(track_stock=True)
        preferred = qs.filter(category__name__iregex=r"(fruit|veg|produce|fresh|dairy|meat)")
        products = list(preferred[:opts["count"]]) or list(qs[:opts["count"]])
        if not products:
            products = list(Product.objects.all()[:opts["count"]])

        if not products:
            self.stdout.write(self.style.ERROR("No products found — run seed_demo first."))
            return

        # batch plan: (days_from_today_for_expiry, qty)
        plan = [(-2, 15), (2, 25), (9, 40)]   # expired, due-soon, ahead

        made = 0
        for p in products:
            p.is_perishable = True
            p.track_stock = True
            if not p.expiry_alert_days:
                p.expiry_alert_days = 5
            p.save(update_fields=["is_perishable", "track_stock", "expiry_alert_days"])

            if opts["reset"]:
                p.batches.all().delete()

            for offset, qty in plan:
                p.add_batch(
                    Decimal(qty),
                    expiry=today + datetime.timedelta(days=offset),
                    received_date=today - datetime.timedelta(days=max(0, 5 - offset)),
                    note="demo batch")
                made += 1
            # keep stock_qty in sync with the batches
            p.stock_qty = p.batch_stock()
            p.save(update_fields=["stock_qty"])
            StockMovement.objects.create(
                product=p, kind=StockMovement.Kind.RESTOCK, change=Decimal(sum(q for _, q in plan)),
                balance_after=p.stock_qty, note="Demo perishable batches")

            self.stdout.write(
                f"  {p.name} ({p.sku}) → perishable, {len(plan)} batches, "
                f"stock {p.stock_qty:g}, nearest expiry {p.nearest_expiry}")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone: {len(products)} product(s) perishable, {made} batches created."))
        self.stdout.write(
            "Now open  Warehouse → Expiring Soon, and run:\n"
            "  USE_CONSOLE_EMAIL=True python manage.py check_expiry   (see the email in the console)\n"
            "  python manage.py check_expiry --dry-run                (list only, no send)")
