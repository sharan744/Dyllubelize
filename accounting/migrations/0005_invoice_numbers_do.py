"""Renumber every existing invoice from INV-00001 style to DO0001 style.

Invoices are renumbered in the order they were created (DO0001 = oldest), and
the old number is also replaced wherever it was written into text: journal
entries, payment / credit-note memos and order history notes.
"""
import re

from django.db import migrations

OLD = re.compile(r"\bINV-\d+\b")

# (app, model, [text fields]) that may mention an invoice number.
TEXT_FIELDS = [
    ("accounting", "JournalEntry", ["memo", "reference"]),
    ("accounting", "JournalLine", ["memo"]),
    ("accounting", "Invoice", ["memo"]),
    ("accounting", "Payment", ["memo", "reference"]),
    ("accounting", "CreditNote", ["reason"]),
    ("orders", "OrderStatusLog", ["note"]),
]


def renumber(apps, schema_editor):
    Invoice = apps.get_model("accounting", "Invoice")
    mapping = {}
    for i, inv in enumerate(Invoice.objects.order_by("id"), start=1):
        new = f"DO{i:04d}"
        if inv.number != new:
            mapping[inv.number] = new
            # temporary value first so the unique index never clashes
            Invoice.objects.filter(pk=inv.pk).update(number=f"TMP{inv.pk}")
    for i, inv in enumerate(Invoice.objects.order_by("id"), start=1):
        Invoice.objects.filter(pk=inv.pk).update(number=f"DO{i:04d}")

    if not mapping:
        return
    sub = lambda text: OLD.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)
    for app, model_name, fields in TEXT_FIELDS:
        try:
            Model = apps.get_model(app, model_name)
        except LookupError:
            continue
        for f in fields:
            for obj in Model.objects.filter(**{f"{f}__contains": "INV-"}):
                val = getattr(obj, f) or ""
                new_val = sub(val)
                if new_val != val:
                    Model.objects.filter(pk=obj.pk).update(**{f: new_val})


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0004_creditnote_invoice_creditnoteline"),
        ("orders", "0004_order_tax_mode"),
    ]
    operations = [migrations.RunPython(renumber, migrations.RunPython.noop)]
