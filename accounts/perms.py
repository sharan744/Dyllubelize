"""Granular, admin-assignable access permissions.

These sit on top of the user's Role. The admin grants any combination of them
per user from the "User Access" screen, so access is controlled by the admin
rather than fixed by role alone.

Keys are plain strings (no dependency on the Role enum) so this module can be
imported from models without a circular import.
"""

# (key, human label) — the fixed checklist shown on the admin User Access page.
ACCESS_PERMS = [
    ("full_access",      "Full access (everything)"),
    ("create_po",        "Create purchase orders"),
    ("apply_payments",   "Apply payments (customers & suppliers)"),
    ("create_customers", "Create customers"),
    ("create_invoices",  "Create invoices"),
    ("view_catalogue",   "View catalogue"),
    ("sales",            "Sales (create orders)"),
]

ACCESS_PERM_KEYS = [k for k, _ in ACCESS_PERMS]

# Sensible defaults per role — used to pre-fill a new user's permissions and to
# backfill existing users, so nobody loses access when this feature ships.
ROLE_DEFAULT_PERMS = {
    "admin":      ["full_access"],
    "team_lead":  ["sales", "create_customers", "create_invoices",
                   "view_catalogue", "create_po", "apply_payments"],
    "sales":      ["sales", "create_customers", "create_invoices",
                   "view_catalogue"],
    "processing": ["view_catalogue", "create_po"],
    "dispatch":   ["view_catalogue"],
    "delivery":   ["view_catalogue"],
}


def default_perms_for_role(role):
    """The default permission keys for a role (empty list if unknown)."""
    return list(ROLE_DEFAULT_PERMS.get(role, []))
