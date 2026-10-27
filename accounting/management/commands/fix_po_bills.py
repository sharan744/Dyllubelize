"""One-off: convert existing received POs' supplier bills to GOODS-ONLY and
re-post their freight/duty as separate landed-cost expense entries.

Safe by default (dry-run). Only touches bills that have NO payment recorded.

    python manage.py fix_po_bills            # dry-run — shows what it would do
    python manage.py fix_po_bills --apply    # actually make the changes
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import PurchaseOrder
from accounting import services


class Command(BaseCommand):
    help = "Rebuild existing received POs' bills to goods-only; post expenses separately."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Actually make the changes (default is a dry-run).")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        fixed = skipped = already = 0
        for po in PurchaseOrder.objects.filter(status=PurchaseOrder.Status.RECEIVED):
            bill = po.bills.first()
            if not bill:
                continue
            exp_lines = bill.lines.filter(description__startswith="Expense —")
            has_separate = services._po_expense_entries(po).exists()
            if not exp_lines.exists():
                if has_separate:
                    already += 1
                continue
            if bill.amount_paid and bill.amount_paid > 0:
                self.stdout.write(f"SKIP {po.po_no}: bill {bill.number} has a payment "
                                  f"({bill.amount_paid}) — reverse it first, then re-run.")
                skipped += 1
                continue
            self.stdout.write(
                f"{'FIXING' if apply else 'WOULD FIX'} {po.po_no}: bill {bill.number} — "
                f"remove {exp_lines.count()} expense line(s) from the supplier bill and "
                f"post them to Accrued Landed Costs.")
            if apply:
                with transaction.atomic():
                    exp_lines.delete()
                    services.post_bill(bill, user=None)                 # repost goods-only
                    services._post_po_expenses(po, bill, user=None)     # expenses separate
                    bill.recalc_status()
            fixed += 1

        self.stdout.write(self.style.SUCCESS(
            f"{'Applied' if apply else 'Dry-run'}: {fixed} PO(s) "
            f"{'fixed' if apply else 'to fix'}, {skipped} skipped (paid), "
            f"{already} already migrated."))
        if not apply and fixed:
            self.stdout.write("Re-run with --apply to make these changes.")
