"""
Find perishable stock batches that are expired or nearing expiry and email
admin + team. Run manually, from OS cron/Task Scheduler, or via the built-in
APScheduler (see core/scheduler.py).

    python manage.py check_expiry            # respects each product's alert window
    python manage.py check_expiry --days 5   # override: anything due within 5 days
    python manage.py check_expiry --dry-run  # list only, don't send email
"""
import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Email admin/team about perishable stock batches nearing expiry (FEFO)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None,
                            help="Alert horizon in days (overrides each product's setting).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would be sent without emailing.")
        parser.add_argument("--to", default=None,
                            help="Send the alert to this address (comma-separated) "
                                 "instead of the admin/team recipients — handy for testing.")

    def handle(self, *args, **opts):
        from catalogue.models import StockBatch
        from core.notifications import notify_expiring
        today = timezone.localdate()

        qs = (StockBatch.objects.filter(qty_remaining__gt=0)
              .exclude(expiry_date=None).select_related("product"))

        due = []
        for b in qs:
            horizon = opts["days"] if opts["days"] is not None else (
                b.product.expiry_alert_days or 7)
            if b.expiry_date <= today + datetime.timedelta(days=horizon):
                due.append(b)

        if not due:
            self.stdout.write(self.style.SUCCESS("No batches nearing expiry."))
            return

        self.stdout.write(f"{len(due)} batch(es) expired or nearing expiry:")
        for b in due:
            d = (b.expiry_date - today).days
            self.stdout.write(
                f"  - {b.product.name} ({b.product.sku}): {b.qty_remaining:g} left, "
                f"exp {b.expiry_date} ({d}d)")

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — no email sent."))
            return

        # warn if SMTP isn't configured (otherwise the send fails silently)
        from django.conf import settings
        pwd = getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""
        backend = getattr(settings, "EMAIL_BACKEND", "")
        if "console" not in backend and ("PASTE" in pwd or not pwd):
            self.stdout.write(self.style.WARNING(
                "Email password not set in settings (EMAIL_HOST_PASSWORD). "
                "Real delivery will fail silently — set your Gmail App Password first, "
                "or use the console backend to preview:\n"
                "  set USE_CONSOLE_EMAIL=True && python manage.py check_expiry --to <email>"))

        recipients = None
        if opts["to"]:
            recipients = [a.strip() for a in opts["to"].split(",") if a.strip()]

        n = notify_expiring(due, recipients=recipients)
        # mark so we don't re-alert the same batch every run on the same day
        for b in due:
            b.alerted_at = today
            b.save(update_fields=["alerted_at"])
        self.stdout.write(self.style.SUCCESS(f"Expiry alert emailed to {n} recipient(s)."))