from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0003_po_usd_landed_cost"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorderline",
            name="unit_cost",
            field=models.DecimalField(max_digits=16, decimal_places=6, default=0),
        ),
    ]
