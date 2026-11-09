from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from payment_account.models import Account
from payment_account.services import get_balance
from product.models import Category, Product, SubCategory
from supplier.models import Supplier
from warehouse.models import Warehouse

from .models import PurchaseAdjustmentType
from .services import cancel_purchase, save_purchase


class PurchaseServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name='Cash', opening_balance=Decimal('1000'), currency='BDT')
        cls.supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.warehouse = Warehouse.objects.create(name='W', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        cls.p1 = Product.objects.create(subcategory=sub, name='P1')
        cls.p2 = Product.objects.create(subcategory=sub, name='P2')
        cls.p3 = Product.objects.create(subcategory=sub, name='P3')
        cls.delivery = PurchaseAdjustmentType.objects.create(name='Delivery', type='add')
        cls.discount = PurchaseAdjustmentType.objects.create(name='Discount', type='deduct')

    def header(self, **kw):
        values = dict(
            warehouse=self.warehouse, supplier=self.supplier, account=self.account,
            date=date.today(), status='paid', note='',
        )
        values.update(kw)
        return values

    def line(self, product, qty, price, **kw):
        return dict(product=product, quantity=qty, purchase_price=Decimal(price), sale_price=Decimal('99'), **kw)

    def test_header_adjustment_split_by_value(self):
        purchase = save_purchase(
            header=self.header(),
            lines=[self.line(self.p1, 10, '5'), self.line(self.p2, 5, '20')],
            adjustments=[(self.delivery, Decimal('30'))],
        )
        a, b = purchase.lots.order_by('id')
        self.assertEqual(a.landed_cost, Decimal('6.0000'))   # (50 + 10) / 10
        self.assertEqual(b.landed_cost, Decimal('24.0000'))  # (100 + 20) / 5
        self.assertEqual(purchase.subtotal, Decimal('150'))
        self.assertEqual(purchase.total_cost, Decimal('30'))
        self.assertEqual(purchase.total_amount, Decimal('180'))

    def test_rounding_remainder_goes_to_last_line(self):
        purchase = save_purchase(
            header=self.header(),
            lines=[self.line(self.p1, 1, '10'), self.line(self.p2, 1, '10'), self.line(self.p3, 1, '10')],
            adjustments=[(self.delivery, Decimal('100'))],
        )
        costs = [d.landed_cost for d in purchase.lots.order_by('id')]
        self.assertEqual(costs, [Decimal('43.3300'), Decimal('43.3300'), Decimal('43.3400')])
        self.assertEqual(sum(costs), purchase.total_amount)

    def test_line_discount_and_header_cost(self):
        purchase = save_purchase(
            header=self.header(),
            lines=[
                self.line(self.p1, 10, '5', adjustments=[(self.discount, Decimal('5'))]),
                self.line(self.p2, 5, '20'),
            ],
            adjustments=[(self.delivery, Decimal('30'))],
        )
        a, b = purchase.lots.order_by('id')
        self.assertEqual(a.discount, Decimal('5'))
        self.assertEqual(a.landed_cost, Decimal('5.4310'))   # (45 + 9.31) / 10
        self.assertEqual(b.landed_cost, Decimal('24.1380'))  # (100 + 20.69) / 5
        self.assertEqual(purchase.total_discount, Decimal('5'))
        self.assertEqual(purchase.total_amount, Decimal('175'))

    def test_transaction_created_and_updated_on_edit(self):
        purchase = save_purchase(header=self.header(), lines=[self.line(self.p1, 10, '5')])
        self.assertEqual(purchase.transaction.amount, Decimal('50'))
        self.assertEqual(get_balance(self.account), Decimal('950'))

        txn_id = purchase.transaction_id
        purchase = save_purchase(
            purchase=purchase, header=self.header(), lines=[self.line(self.p1, 10, '8')],
        )
        self.assertEqual(purchase.transaction_id, txn_id)
        self.assertEqual(purchase.transaction.amount, Decimal('80'))
        self.assertEqual(get_balance(self.account), Decimal('920'))

    def test_pending_does_not_touch_balance(self):
        save_purchase(header=self.header(status='pending'), lines=[self.line(self.p1, 10, '5')])
        self.assertEqual(get_balance(self.account), Decimal('1000'))

    def test_edit_replaces_lines(self):
        purchase = save_purchase(header=self.header(), lines=[self.line(self.p1, 2, '5'), self.line(self.p2, 2, '5')])
        purchase = save_purchase(purchase=purchase, header=self.header(), lines=[self.line(self.p3, 4, '5')])
        self.assertEqual(purchase.lots.count(), 1)
        self.assertEqual(purchase.lots.get().remaining_quantity, 4)

    def test_cancel_removes_effect_on_balance(self):
        purchase = save_purchase(header=self.header(), lines=[self.line(self.p1, 10, '5')])
        cancel_purchase(purchase)
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'cancelled')
        self.assertEqual(purchase.transaction.status, 'cancelled')
        self.assertEqual(get_balance(self.account), Decimal('1000'))
        with self.assertRaises(ValidationError):
            save_purchase(purchase=purchase, header=self.header(), lines=[self.line(self.p1, 1, '5')])

    def test_used_stock_blocks_edit_and_cancel(self):
        purchase = save_purchase(header=self.header(), lines=[self.line(self.p1, 10, '5')])
        lot = purchase.lots.get()
        lot.remaining_quantity = 7  # as if 3 were sold
        lot.save()
        with self.assertRaises(ValidationError):
            save_purchase(purchase=purchase, header=self.header(), lines=[self.line(self.p1, 10, '5')])
        with self.assertRaises(ValidationError):
            cancel_purchase(purchase)

    def test_invalid_input_rejected_and_nothing_saved(self):
        from .models import Purchase

        with self.assertRaises(ValidationError):
            save_purchase(header=self.header(), lines=[])
        with self.assertRaises(ValidationError):
            save_purchase(header=self.header(), lines=[self.line(self.p1, 0, '5')])
        with self.assertRaises(ValidationError):  # discount bigger than the purchase
            save_purchase(
                header=self.header(), lines=[self.line(self.p1, 1, '10')],
                adjustments=[(self.discount, Decimal('50'))],
            )
        self.assertFalse(Purchase.objects.exists())
