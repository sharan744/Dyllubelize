from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_purchaseorderexpense"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorder",
            name="exchange_rate",
            field=models.DecimalField(decimal_places=4, default=Decimal("2.00"), max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaseorderline",
            name="unit_cost_usd",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaseorderline",
            name="sell_price",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="purchaseorderexpense",
            name="currency",
            field=models.CharField(
                choices=[("BZD", "BZD"), ("USD", "USD")], default="BZD", max_length=3),
        ),
    ]
