from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalogue", "0008_product_expiry_alert_days_product_is_perishable_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="taxable",
            field=models.BooleanField(
                default=True,
                help_text="Tick if GST (or the configured tax) is charged on this item. "
                          "Untick for tax-exempt items (e.g. some foods).",
                verbose_name="GST / tax applies",
            ),
        ),
    ]
