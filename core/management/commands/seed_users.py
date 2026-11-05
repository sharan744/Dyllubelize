"""Load ONLY the staff user accounts into the database.

This is the user-seeding part of `seed_demo` on its own — it creates the eight
Flujo login accounts (one per role) and nothing else. Safe to run on a live
database: it uses get_or_create, so existing users are left untouched.

Usage:
    python manage.py seed_users
    python manage.py seed_users --password "mypass123"   # set a different password
    python manage.py seed_users --reset                   # delete non-superuser staff first
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User, Role


# (username, first name, last name, role)
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


class Command(BaseCommand):
    help = "Load only the staff user accounts (no catalogue, orders or other data)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="flujo123",
                            help="Password to set for any newly created user (default: flujo123).")
        parser.add_argument("--reset", action="store_true",
                            help="Delete existing non-superuser accounts before loading.")

    @transaction.atomic
    def handle(self, *args, **opts):
        password = opts["password"]

        if opts["reset"]:
            deleted, _ = User.objects.filter(is_superuser=False).delete()
            self.stdout.write(f"Removed {deleted} non-superuser account(s).")

        created_count = 0
        for username, first, last, role in USERS:
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "role": role,
                          "email": f"{username}@udl.bz"},
            )
            if created:
                u.set_password(password)
                if role == Role.ADMIN:
                    u.is_staff = u.is_superuser = True
                u.save()
                created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nUsers ready — {created_count} created, "
            f"{len(USERS) - created_count} already existed."))
        self.stdout.write(f"\nLogin accounts (password for new users: {password}):")
        for username, first, last, role in USERS:
            self.stdout.write(f"  • {username:<11} — {first} {last} ({role})")
