import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.models import Order, OrderStatus, OrderItem
from accounting import services
from accounting.models import (
    Invoice, Payment, DocStatus, PaymentApplication, Account,
    JournalEntry, JournalLine, JournalSource,
)


class Command(BaseCommand):
    help = "Create the default chart of accounts and generate invoices from delivered orders."

    def add_arguments(self, parser):
        parser.add_argument("--invoices", action="store_true",
                            help="Also generate & post invoices from delivered/completed orders.")
        parser.add_argument("--payments", action="store_true",
                            help="Also record payments for ~70%% of generated invoices (demo).")

    def handle(self, *args, **opts):
        created = services.ensure_chart()
        self.stdout.write(self.style.SUCCESS(
            f"Chart of accounts ready ({created} new account(s), "
            f"{Account.objects.count()} total)."))

        # opening balances (once) — so the Balance Sheet reads cleanly
        if not JournalEntry.objects.filter(source=JournalSource.OPENING).exists():
            first = Order.objects.order_by("created_at").first()
            d = (first.created_at.date().replace(month=1, day=1)
                 if first else timezone.localdate().replace(month=1, day=1))
            je = JournalEntry.objects.create(date=d, memo="Opening balances",
                                             source=JournalSource.OPENING, posted=True)
            JournalLine.objects.create(entry=je, account=Account.objects.get(code="1300"),
                                       debit=Decimal("150000"), credit=0, memo="Opening inventory")
            JournalLine.objects.create(entry=je, account=Account.objects.get(code="1010"),
                                       debit=Decimal("80000"), credit=0, memo="Opening bank")
            JournalLine.objects.create(entry=je, account=Account.objects.get(code="3000"),
                                       debit=0, credit=Decimal("230000"), memo="Owner capital")
            self.stdout.write(self.style.SUCCESS("Opening balances posted."))

        if opts["invoices"]:
            # make sure order-item costs are snapshotted so COGS + margins are real
            fixed = 0
            for it in OrderItem.objects.select_related("product"):
                if (not it.unit_cost or it.unit_cost == 0) and it.product and it.product.cost_price:
                    it.unit_cost = it.product.cost_price
                    it.save(update_fields=["unit_cost"])
                    fixed += 1
            if fixed:
                self.stdout.write(f"Snapshotted cost on {fixed} order line(s).")

            orders = (Order.objects
                      .filter(status__in=[OrderStatus.DELIVERED, OrderStatus.COMPLETED])
                      .prefetch_related("items"))
            made = 0
            for o in orders:
                if getattr(o, "invoice", None):
                    continue
                inv = services.invoice_from_order(o, post=False)
                d = o.completed_at or o.confirmed_at or o.created_at
                inv.date = timezone.localtime(d).date()
                inv.save(update_fields=["date"])
                services.post_invoice(inv)
                made += 1
            self.stdout.write(self.style.SUCCESS(f"Generated {made} invoice(s) from orders."))

            if opts["payments"]:
                bank = Account.objects.filter(is_bank=True).first()
                paid = 0
                invs = list(Invoice.objects.exclude(status=DocStatus.VOID).order_by("date"))
                for idx, inv in enumerate(invs):
                    # pay every invoice except roughly the most recent third (keeps AR realistic)
                    if idx % 10 < 3 and inv == invs[-1]:
                        continue
                    if idx >= len(invs) - max(1, len(invs) // 4):
                        continue  # leave the newest quarter open / overdue
                    pay = Payment.objects.create(
                        customer=inv.customer, date=inv.date, amount=inv.total,
                        deposit_account=bank, method="bank",
                        memo=f"Payment for {inv.number}")
                    PaymentApplication.objects.create(payment=pay, invoice=inv, amount=inv.total)
                    services.post_payment(pay)
                    paid += 1
                self.stdout.write(self.style.SUCCESS(f"Recorded {paid} customer payment(s)."))
