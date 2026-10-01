"""Seed the database with a full, realistic dataset spanning past, present and future.

Covers: users, catalogue (cost + reorder), suppliers, purchase orders,
customer-specific pricing + quantity breaks, customers (Belize + Indian),
orders across ~12 months in every status, dispatches, deliveries (POD),
returns (good + damaged), and low-stock items — so the dashboard, accounting,
reports and inventory pages are all populated.
"""
import random
from decimal import Decimal
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from accounts.models import User, Role
from catalogue.models import (Category, Product, StockMovement,
                              PriceBreak, CustomerPrice)
from orders.models import Customer, Order, OrderItem, OrderStatus
from dispatchapp.models import Dispatch
from delivery.models import DeliveryConfirmation
from inventory.models import Supplier, PurchaseOrder, PurchaseOrderLine
from returnsapp.models import Return, ReturnLine
from core.models import SiteSetting


CATALOGUE = {
    "Soft Drinks": [
        ("Cola Classic 355ml Can", "SD-COLA-355", "bottle", 12.50),
        ("Cola Classic 2L Bottle", "SD-COLA-2L", "bottle", 28.00),
        ("Sparkling Lime 600ml", "SD-LIME-600", "bottle", 15.00),
        ("Orange Soda 355ml Can", "SD-ORNG-355", "bottle", 12.50),
        ("Mineral Water 1L", "SD-WATR-1L", "bottle", 9.00),
        ("Tamarind Soda 355ml", "SD-TAMA-355", "bottle", 13.00),
    ],
    "Spices": [
        ("Chili Powder 100g", "SP-CHIL-100", "pack", 22.00),
        ("Ground Cumin 100g", "SP-CUMI-100", "pack", 26.00),
        ("Oregano 50g", "SP-OREG-050", "pack", 18.00),
        ("Cinnamon Sticks 50g", "SP-CINN-050", "pack", 30.00),
        ("Black Pepper 100g", "SP-PEPP-100", "pack", 34.00),
    ],
    "Fruits & Vegetables": [
        ("Roma Tomatoes", "FV-TOMA-KG", "kg", 24.00),
        ("White Onions", "FV-ONIO-KG", "kg", 19.00),
        ("Hass Avocado", "FV-AVOC-KG", "kg", 68.00),
        ("Serrano Chili", "FV-SERR-KG", "kg", 40.00),
        ("Limes", "FV-LIME-KG", "kg", 22.00),
        ("Bananas", "FV-BANA-KG", "kg", 16.00),
    ],
    "Snacks": [
        ("Tortilla Chips 200g", "SN-TORT-200", "pack", 20.00),
        ("Salted Peanuts 150g", "SN-PNUT-150", "pack", 17.00),
        ("Spicy Corn Puffs 90g", "SN-CORN-090", "pack", 14.00),
        ("Mixed Nuts 250g", "SN-MXNT-250", "pack", 48.00),
    ],
}

USERS = [
    ("admin", "Andrea", "Gill", Role.ADMIN),
    ("sales", "Shanice", "Robateau", Role.SALES),
    ("sales2", "Keisha", "Bood", Role.SALES),
    ("sales3", "Amit", "Verma", Role.SALES),
    ("teamlead", "Carlos", "Mendez", Role.TEAM_LEAD),
    ("processing", "Devon", "Hyde", Role.PROCESSING),
    ("dispatch", "Luisa", "Tzul", Role.DISPATCH),
    ("delivery", "Marlon", "Flowers", Role.DELIVERY),
]

# (company, contact, mobile, address, tax_id, email)
CUSTOMERS = [
    # Belize
    ("Brodies Supermarket", "James Brodie", "5016012301",
     "Regent Street, Belize City, Belize", "TIN-100234", "orders@brodies.bz"),
    ("Save-U Supermarket", "Maria Chan", "5016012302",
     "San Cas Plaza, Belize City, Belize", "TIN-100235", "buyer@saveu.bz"),
    ("Tienda La Placita", "Rosa Cus", "5016012303",
     "Central Park, San Ignacio, Cayo", "", "laplacita@gmail.com"),
    ("Ramon's Village Resort", "Luis Ramos", "5016012304",
     "Coconut Drive, San Pedro, Ambergris Caye", "TIN-100236", "purchasing@ramons.bz"),
    ("Corozal Mini Mart", "Patricia Novelo", "5016012305",
     "4th Avenue, Corozal Town, Belize", "", ""),
    # Indian
    ("Sharma General Store", "Rajesh Sharma", "919812345601",
     "MG Road, Bengaluru, Karnataka 560001, India", "GSTIN-29ABCDE1234F1", "rajesh@sharmastore.in"),
    ("Patel Wholesale Mart", "Nirav Patel", "919812345602",
     "Ashram Road, Ahmedabad, Gujarat 380009, India", "GSTIN-24PQRSX5678L1", "nirav@patelmart.in"),
    ("Iyer Provision Stores", "Lakshmi Iyer", "919812345603",
     "T. Nagar, Chennai, Tamil Nadu 600017, India", "GSTIN-33IYERZ9012M1", "lakshmi@iyerstores.in"),
    ("Singh Kirana Bazaar", "Harpreet Singh", "919812345604",
     "Model Town, Ludhiana, Punjab 141002, India", "", "harpreet@singhbazaar.in"),
    ("Reddy Super Bazaar", "Anitha Reddy", "919812345605",
     "Banjara Hills, Hyderabad, Telangana 500034, India", "GSTIN-36REDDY3456N1", "anitha@reddybazaar.in"),
]

DRIVERS = [
    ("Isuzu NPR — Plate C-12345", "Kevin Waight", "5016099001"),
    ("Ford Transit — Plate D-44821", "Errol Baptist", "5016099002"),
    ("Tata 407 — Plate KA-01-2244", "Suresh Kumar", "919800011122"),
]


class Command(BaseCommand):
    help = "Load a full demo dataset across past, present and future."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing data before seeding.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["reset"]:
            self.stdout.write("Resetting data…")
            ReturnLine.objects.all().delete()
            Return.objects.all().delete()
            try:
                from returnsapp.models import ReturnPhoto
                ReturnPhoto.objects.all().delete()
            except Exception:
                pass
            PurchaseOrderLine.objects.all().delete()
            PurchaseOrder.objects.all().delete()
            Supplier.objects.all().delete()
            StockMovement.objects.all().delete()
            CustomerPrice.objects.all().delete()
            PriceBreak.objects.all().delete()
            DeliveryConfirmation.objects.all().delete()
            Dispatch.objects.all().delete()
            OrderItem.objects.all().delete()
            Order.objects.all().delete()
            Customer.objects.all().delete()
            Product.objects.all().delete()
            Category.objects.all().delete()
            User.objects.filter(is_superuser=False).delete()

        random.seed(11)
        now = timezone.now()

        # ---- Site settings ----
        site = SiteSetting.get()
        site.company_name = "United Distributors Ltd"
        site.tagline = "Distribution & Supply"
        site.address = "Mile 3 George Price Highway, Belize City, Belize"
        site.phone = "+501 223 4567"
        site.email = "sales@udl.bz"
        site.tax_id = "TIN-000123456"
        site.currency_symbol = "$"
        site.currency_code = "BZD"
        site.tax_enabled = True
        site.tax_label = "GST"
        site.tax_percent = Decimal("12.5")
        site.quote_validity_days = 15
        site.save()

        # ---- Users ----
        users = {}
        for username, first, last, role in USERS:
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "role": role,
                          "email": f"{username}@udl.bz"},
            )
            if created:
                u.set_password("flujo123")
                if role == Role.ADMIN:
                    u.is_staff = u.is_superuser = True
                u.save()
            users[role] = u
        sales, tl = users[Role.SALES], users[Role.TEAM_LEAD]
        proc, disp, deliv = users[Role.PROCESSING], users[Role.DISPATCH], users[Role.DELIVERY]
        salespeople = list(User.objects.filter(role=Role.SALES))
        self.stdout.write(self.style.SUCCESS(f"Users ready ({len(USERS)})."))

        # ---- Catalogue (cost + reorder + stock) ----
        for cat_name, products in CATALOGUE.items():
            cat, _ = Category.objects.get_or_create(name=cat_name)
            for name, sku, unit, price in products:
                price_d = Decimal(str(price))
                Product.objects.update_or_create(
                    sku=sku,
                    defaults={"name": name, "category": cat, "unit": unit,
                              "selling_price": price_d,
                              "cost_price": (price_d * Decimal("0.62")).quantize(Decimal("0.01")),
                              "stock_qty": Decimal(str(random.choice([1800, 2400, 3000]))),
                              "reorder_point": Decimal("400"), "track_stock": True},
                )
        products = list(Product.objects.all())
        self.stdout.write(self.style.SUCCESS(
            f"Catalogue ready ({Category.objects.count()} categories, {len(products)} products)."))

        # ---- Suppliers ----
        suppliers = []
        for nm, cp, ph, em, addr in [
            ("Caribbean Beverage Distributors", "Alicia Gomez", "5012235000", "sales@caribbev.bz", "Freetown Rd, Belize City"),
            ("Global Spice Traders", "Mohan Nair", "919845000111", "mohan@globalspice.in", "Cochin, Kerala, India"),
            ("Fresh Farms Produce", "Daniel Cho", "5016223344", "orders@freshfarms.bz", "Spanish Lookout, Cayo"),
            ("Snack World Imports", "Priya Menon", "919845000222", "priya@snackworld.in", "Mumbai, Maharashtra, India"),
        ]:
            s, _ = Supplier.objects.get_or_create(name=nm, defaults={
                "contact_person": cp, "phone": ph, "email": em, "address": addr})
            suppliers.append(s)

        # ---- Customers ----
        customers = []
        for name, contact, mobile, addr, tax, email in CUSTOMERS:
            c, _ = Customer.objects.get_or_create(company_name=name, defaults={
                "name": contact, "contact_person": contact, "mobile": mobile,
                "email": email, "billing_address": addr, "delivery_address": addr,
                "tax_id": tax, "created_by": sales})
            customers.append(c)
        self.stdout.write(self.style.SUCCESS(f"Customers ready ({len(customers)})."))

        # ---- Pricing: quantity breaks + customer overrides ----
        for p in random.sample(products, 6):
            PriceBreak.objects.get_or_create(product=p, min_qty=Decimal("50"),
                defaults={"price": (p.selling_price * Decimal("0.92")).quantize(Decimal("0.01"))})
            PriceBreak.objects.get_or_create(product=p, min_qty=Decimal("100"),
                defaults={"price": (p.selling_price * Decimal("0.85")).quantize(Decimal("0.01"))})
        for cust in customers[:3]:
            for p in random.sample(products, 4):
                CustomerPrice.objects.get_or_create(customer=cust, product=p,
                    defaults={"price": (p.selling_price * Decimal("0.90")).quantize(Decimal("0.01"))})

        if Order.objects.exists():
            self.stdout.write("Orders already present — skipping order generation.")
            self._summary()
            return

        # ---------- Order helpers ----------
        def build(customer, when, n_items=None):
            n_items = n_items or random.randint(2, 5)
            o = Order.objects.create(customer=customer, salesperson=random.choice(salespeople),
                                     remarks=random.choice(["", "Handle with care.",
                                                            "Call before delivery.", "Fragile items."]))
            for p in random.sample(products, n_items):
                qty = Decimal(str(random.choice([5, 10, 12, 24, 36, 48, 60, 100])))
                OrderItem.objects.create(
                    order=o, product=p, product_name=p.name, sku=p.sku,
                    unit=p.get_unit_display(), unit_price=p.selling_price, quantity=qty)
            if random.random() < 0.5:
                o.discount_percent = Decimal(str(random.choice([0, 5, 10])))
                o.save(update_fields=["discount_percent"])
            return o

        def backdate(o, created, confirmed=None, completed=None):
            Order.objects.filter(pk=o.pk).update(
                created_at=created, confirmed_at=confirmed, completed_at=completed,
                updated_at=completed or confirmed or created)

        def full_cycle(customer, when):
            """Completed order with dispatch + POD, dated around `when`."""
            o = build(customer, when)
            for st, who in [(OrderStatus.SUBMITTED, sales), (OrderStatus.CONFIRMED, tl),
                            (OrderStatus.PROCESSING, proc), (OrderStatus.READY, proc)]:
                o.set_status(st, who)
            veh, drv, dc = random.choice(DRIVERS)
            dsp = Dispatch.objects.create(
                vehicle_details=veh, driver_name=drv, driver_contact=dc,
                dispatch_date=when.date(),
                expected_delivery_date=(when + timedelta(days=1)).date(),
                created_by=disp, status=Dispatch.Status.DELIVERED)
            dsp.orders.add(o)
            o.set_status(OrderStatus.DISPATCHED, disp, f"On {dsp.dispatch_no}")
            DeliveryConfirmation.objects.create(
                order=o, dispatch=dsp, delivered_at=when, delivered_by=deliv,
                received_by=o.customer.contact_person,
                signature_name=o.customer.contact_person,
                remarks="Received in good condition.")
            o.set_status(OrderStatus.DELIVERED, deliv)
            o.set_status(OrderStatus.COMPLETED, deliv)
            Dispatch.objects.filter(pk=dsp.pk).update(created_at=when - timedelta(days=1))
            backdate(o, when - timedelta(days=3), when - timedelta(days=2), when)
            return o

        # ---------- PAST: completed orders spread across ~12 months ----------
        completed = []
        for months_ago in range(12, 0, -1):
            base = now - timedelta(days=30 * months_ago)
            for _ in range(random.randint(3, 6)):
                when = base + timedelta(days=random.randint(0, 27),
                                        hours=random.randint(8, 17))
                completed.append(full_cycle(random.choice(customers), when))
        # a couple in a previous calendar year (for the yearly view)
        for _ in range(3):
            when = now - timedelta(days=random.randint(400, 500))
            completed.append(full_cycle(random.choice(customers), when))
        # this week (for the weekly view)
        for _ in range(3):
            when = now - timedelta(days=random.randint(0, 6), hours=random.randint(1, 8))
            completed.append(full_cycle(random.choice(customers), when))

        # ---------- PAST: cancellations / returns ----------
        for _ in range(3):
            when = now - timedelta(days=random.randint(20, 200))
            o = build(random.choice(customers), when)
            o.set_status(OrderStatus.SUBMITTED, sales)
            o.set_status(OrderStatus.CANCELLED, tl, "Customer cancelled")
            backdate(o, when, None, None)

        # returns (RMA) on a few completed orders — some good, some damaged
        for o in random.sample(completed, 4):
            r = Return.objects.create(order=o, reason=random.choice(["damaged", "expired", "wrong_item"]),
                                      reason_note="Customer reported issue", created_by=disp)
            for it in o.items.all()[:2]:
                q = it.quantity
                good = (q // 2)
                dmg = q - good
                ReturnLine.objects.create(ret=r, product=it.product, product_name=it.product_name,
                    sku=it.sku, unit=it.unit, unit_price=it.unit_price,
                    good_qty=good, damaged_qty=dmg)
            r.process(user=disp)
            Return.objects.filter(pk=r.pk).update(created_at=o.completed_at + timedelta(days=2),
                                                  processed_at=o.completed_at + timedelta(days=2))

        # ---------- PRESENT: live pipeline in every queue ----------
        def to_status(customer, target):
            o = build(customer, now)
            chain = [OrderStatus.SUBMITTED, OrderStatus.CONFIRMED, OrderStatus.PROCESSING, OrderStatus.READY]
            whos = [sales, tl, proc, proc]
            for st, who in zip(chain, whos):
                o.set_status(st, who)
                if st == target:
                    break
            backdate(o, now - timedelta(days=random.randint(0, 4)))
            return o

        for _ in range(3):
            build(random.choice(customers), now)  # drafts
        for _ in range(3):
            to_status(random.choice(customers), OrderStatus.SUBMITTED)
        for _ in range(2):
            to_status(random.choice(customers), OrderStatus.CONFIRMED)
        for _ in range(2):
            to_status(random.choice(customers), OrderStatus.PROCESSING)
        for _ in range(3):
            to_status(random.choice(customers), OrderStatus.READY)
        # a couple dispatched but not yet delivered (awaiting delivery team)
        for _ in range(2):
            o = to_status(random.choice(customers), OrderStatus.READY)
            veh, drv, dc = random.choice(DRIVERS)
            dsp = Dispatch.objects.create(vehicle_details=veh, driver_name=drv, driver_contact=dc,
                dispatch_date=now.date(), expected_delivery_date=(now + timedelta(days=2)).date(),
                created_by=disp, status=Dispatch.Status.DISPATCHED)
            dsp.orders.add(o)
            o.set_status(OrderStatus.DISPATCHED, disp, f"On {dsp.dispatch_no}")

        # ---------- PURCHASE ORDERS: past received + future expected ----------
        def make_po(supplier, when, status, expected=None):
            po = PurchaseOrder.objects.create(supplier=supplier, created_by=proc,
                order_date=when.date(), expected_date=expected, status=PurchaseOrder.Status.DRAFT)
            for p in random.sample(products, random.randint(3, 6)):
                PurchaseOrderLine.objects.create(po=po, product=p,
                    qty_ordered=Decimal(str(random.choice([100, 200, 300, 500]))),
                    unit_cost=(p.cost_price or (p.selling_price * Decimal("0.6"))).quantize(Decimal("0.01")))
            if status == PurchaseOrder.Status.RECEIVED:
                po.receive(user=proc)
                PurchaseOrder.objects.filter(pk=po.pk).update(
                    created_at=when, received_at=when + timedelta(days=3))
            else:
                po.status = status
                po.save(update_fields=["status"])
                PurchaseOrder.objects.filter(pk=po.pk).update(created_at=when)
            return po

        make_po(suppliers[0], now - timedelta(days=60), PurchaseOrder.Status.RECEIVED)
        make_po(suppliers[1], now - timedelta(days=25), PurchaseOrder.Status.RECEIVED)
        make_po(suppliers[2], now - timedelta(days=2), PurchaseOrder.Status.ORDERED,
                expected=(now + timedelta(days=7)).date())     # future arrival
        make_po(suppliers[3], now, PurchaseOrder.Status.DRAFT,
                expected=(now + timedelta(days=14)).date())    # future

        # ---------- Low stock: force a few below reorder ----------
        for p in random.sample(products, 3):
            p.stock_qty = Decimal(str(random.choice([80, 150, 220])))
            p.save(update_fields=["stock_qty"])

        self._summary()

    def _summary(self):
        self.stdout.write(self.style.SUCCESS("\nFull demo dataset loaded."))
        self.stdout.write(f"  Orders: {Order.objects.count()} · "
                          f"Dispatches: {Dispatch.objects.count()} · "
                          f"Returns: {Return.objects.count()} · "
                          f"POs: {PurchaseOrder.objects.count()}")
        self.stdout.write("\nLogin accounts (password: flujo123):")
        for username, first, last, role in USERS:
            self.stdout.write(f"  • {username:<11} — {first} {last} ({role})")
        self.stdout.write(self.style.WARNING("\nAdmin can also open /admin/ for full management."))
