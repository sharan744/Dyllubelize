from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseOrderExpense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("po", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="expenses", to="inventory.purchaseorder")),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
