from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0003_orderitem_unit_cost"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="tax_mode",
            field=models.CharField(
                choices=[("GST", "GST"), ("NON", "Non")],
                default="GST",
                help_text="GST = charge the GST rate from Admin & Settings; Non = tax-exempt.",
                max_length=3,
            ),
        ),
    ]
