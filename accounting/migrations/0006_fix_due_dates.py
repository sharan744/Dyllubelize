"""Fix invoices / supplier bills whose Terms were edited but whose due date
was not updated (due date = date + terms days)."""
import datetime

from django.db import migrations


def fix(apps, schema_editor):
    for name in ("Invoice", "Bill"):
        Model = apps.get_model("accounting", name)
        for obj in Model.objects.exclude(date=None).only("id", "date", "terms_days", "due_date"):
            want = obj.date + datetime.timedelta(days=obj.terms_days or 0)
            if obj.due_date != want:
                Model.objects.filter(pk=obj.pk).update(due_date=want)


class Migration(migrations.Migration):
    dependencies = [("accounting", "0005_invoice_numbers_do")]
    operations = [migrations.RunPython(fix, migrations.RunPython.noop)]
