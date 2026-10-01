from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_sitesetting_incentive_percent"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesetting",
            name="accounts_follow_invoice_visibility",
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When enabled, Accounts reports follow the '
                    'invoice "Show in UI" setting.'
                ),
            ),
        ),
    ]