"""Pre-build the small product photos used by the mobile app.

    python manage.py make_thumbs

Safe to run any time (only missing ones are created). Run once after deploy so
the first catalogue load on the phones is instant.
"""
from django.core.management.base import BaseCommand

from catalogue.models import Product
from catalogue.thumbs import ensure_thumb


class Command(BaseCommand):
    help = "Create small thumbnails for all product photos."

    def handle(self, *args, **opts):
        done = failed = 0
        for p in Product.objects.exclude(image="").exclude(image=None).iterator():
            if ensure_thumb(p.image):
                done += 1
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  skipped {p.sku}: photo missing/unreadable"))
        self.stdout.write(self.style.SUCCESS(f"Thumbnails ready: {done}  (skipped {failed})"))
