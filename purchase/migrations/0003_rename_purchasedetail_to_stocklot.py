from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Rename PurchaseDetail to StockLot in place, keeping all existing rows."""

    dependencies = [
        ('product', '0002_alter_product_table'),
        ('purchase', '0002_purchase_purchasedetail_purchaseadjustment_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(model_name='purchasedetail', name='purchase_detail_quantity_positive'),
        migrations.RemoveConstraint(model_name='purchasedetail', name='purchase_detail_remaining_lte_quantity'),
        migrations.RemoveConstraint(model_name='purchasedetail', name='purchase_detail_prices_non_negative'),
        migrations.RenameModel(old_name='PurchaseDetail', new_name='StockLot'),
        migrations.AlterModelTable(name='stocklot', table='stock_lot'),
        migrations.RenameField(model_name='purchaseadjustment', old_name='detail', new_name='lot'),
        migrations.AlterField(
            model_name='stocklot',
            name='purchase',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name='lots', to='purchase.purchase',
            ),
        ),
        migrations.AlterField(
            model_name='stocklot',
            name='product',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='stock_lots', to='product.product',
            ),
        ),
        migrations.AddConstraint(
            model_name='stocklot',
            constraint=models.CheckConstraint(check=models.Q(('quantity__gt', 0)), name='stock_lot_quantity_positive'),
        ),
        migrations.AddConstraint(
            model_name='stocklot',
            constraint=models.CheckConstraint(
                check=models.Q(('remaining_quantity__lte', models.F('quantity'))),
                name='stock_lot_remaining_lte_quantity',
            ),
        ),
        migrations.AddConstraint(
            model_name='stocklot',
            constraint=models.CheckConstraint(
                check=models.Q(('purchase_price__gte', 0), ('sale_price__gte', 0)),
                name='stock_lot_prices_non_negative',
            ),
        ),
    ]
