from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0002_invoice_show_in_ui"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoiceline",
            name="taxable",
            field=models.BooleanField(default=True),
        ),
    ]
