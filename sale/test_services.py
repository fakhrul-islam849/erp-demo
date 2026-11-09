from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from payment_account.models import Account, Transaction
from payment_account.services import get_balance
from product.models import Category, Product, SubCategory
from purchase.models import StockLot
from purchase.services import save_purchase
from supplier.models import Supplier
from warehouse.models import Warehouse

from .models import Sale, SaleAdjustmentType
from .services import damage_sale, refund_sale, return_sale, save_sale

D = Decimal


class SaleServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        cls.supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.wh_a = Warehouse.objects.create(name='A', marketplace_name='m', marketplace_location='l')
        cls.wh_b = Warehouse.objects.create(name='B', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        cls.p1 = Product.objects.create(subcategory=sub, name='P1')
        cls.p2 = Product.objects.create(subcategory=sub, name='P2')
        cls.delivery = SaleAdjustmentType.objects.create(name='Delivery', type='add')
        cls.discount = SaleAdjustmentType.objects.create(name='Discount', type='deduct')

    def setUp(self):
        # A holds 10 x P1 (sale price 8) and 4 x P2 (sale price 15); B holds 5 x P1 (sale price 9)
        purchase_a = save_purchase(
            header=dict(warehouse=self.wh_a, supplier=self.supplier, account=self.account,
                        date=date.today(), status='paid', note=''),
            lines=[
                dict(product=self.p1, quantity=10, purchase_price=D('5'), sale_price=D('8')),
                dict(product=self.p2, quantity=4, purchase_price=D('10'), sale_price=D('15')),
            ],
        )
        self.lot1, self.lot2 = purchase_a.lots.order_by('id')
        purchase_b = save_purchase(
            header=dict(warehouse=self.wh_b, supplier=self.supplier, account=self.account,
                        date=date.today(), status='paid', note=''),
            lines=[dict(product=self.p1, quantity=5, purchase_price=D('6'), sale_price=D('9'))],
        )
        self.lot_b = purchase_b.lots.get()
        self.balance_before = get_balance(self.account)

    def header(self, **kw):
        return dict(account=self.account, date=date.today(), details='', **kw)

    def remaining(self, lot):
        lot.refresh_from_db()
        return lot.remaining_quantity

    def sell(self, lines=None, adjustments=(), **header):
        if lines is None:
            lines = [dict(lot=self.lot1, quantity=3)]
        return save_sale(header=self.header(**header), lines=lines, adjustments=adjustments)

    # ---- create and totals -------------------------------------------------

    def test_sale_deducts_stock_and_uses_lot_price(self):
        sale = self.sell()
        line = sale.lines.get()
        self.assertEqual(self.remaining(self.lot1), 7)
        self.assertEqual(line.sale_price, D('8'))
        self.assertEqual(line.line_total, D('24.00'))
        self.assertEqual(sale.total_amount, D('24.00'))
        self.assertEqual(sale.status, Sale.Status.SOLD)

    def test_sale_can_mix_lots_from_different_warehouses(self):
        sale = self.sell(lines=[dict(lot=self.lot1, quantity=2), dict(lot=self.lot_b, quantity=1)])
        self.assertEqual(sale.total_amount, D('25.00'))
        self.assertEqual(self.remaining(self.lot1), 8)
        self.assertEqual(self.remaining(self.lot_b), 4)

    def test_line_and_sale_adjustments_flow_into_the_total(self):
        sale = self.sell(
            lines=[dict(lot=self.lot1, quantity=3, adjustments=[(self.delivery, D('2')), (self.discount, D('1'))])],
            adjustments=[(self.delivery, D('10')), (self.discount, D('4'))],
        )
        line = sale.lines.get()
        self.assertEqual((line.add_total, line.deduct_total, line.line_total), (D('2'), D('1'), D('25.00')))
        self.assertEqual(sale.subtotal, D('25.00'))
        self.assertEqual((sale.lines_add, sale.lines_deduct), (D('2'), D('1')))
        self.assertEqual((sale.sale_add, sale.sale_deduct), (D('10'), D('4')))
        self.assertEqual(sale.total_amount, D('31.00'))

    def test_cannot_sell_more_than_remaining(self):
        with self.assertRaises(ValidationError):
            self.sell(lines=[dict(lot=self.lot1, quantity=11)])
        self.assertEqual(self.remaining(self.lot1), 10)
        self.assertEqual(Sale.objects.count(), 0)

    def test_failed_sale_leaves_no_stock_change(self):
        with self.assertRaises(ValidationError):
            self.sell(lines=[dict(lot=self.lot1, quantity=3), dict(lot=self.lot2, quantity=99)])
        self.assertEqual(self.remaining(self.lot1), 10)

    def test_validation_errors(self):
        for lines in (
            [],
            [dict(lot=self.lot1, quantity=0)],
            [dict(lot=self.lot1, quantity=1), dict(lot=self.lot1, quantity=1)],
            [dict(lot=self.lot1, quantity=1, adjustments=[(self.delivery, D('0'))])],
            [dict(lot=self.lot1, quantity=1, adjustments=[(self.discount, D('9'))])],  # bigger than the line
        ):
            with self.subTest(lines=lines), self.assertRaises(ValidationError):
                self.sell(lines=lines)

    def test_sale_discount_larger_than_total_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.sell(adjustments=[(self.discount, D('100'))])

    def test_lot_of_unconfirmed_stock_is_not_available(self):
        self.lot1.purchase.status = 'cancelled'
        self.lot1.purchase.save()
        with self.assertRaises(ValidationError):
            self.sell()

    # ---- payment -----------------------------------------------------------

    def test_pending_sale_creates_no_transaction(self):
        sale = self.sell()
        self.assertIsNone(sale.transaction)
        self.assertEqual(get_balance(self.account), self.balance_before)

    def test_received_sale_adds_total_to_account(self):
        sale = self.sell(adjustments=[(self.delivery, D('6'))], payment_status='received')
        self.assertEqual(sale.transaction.amount, D('30.00'))
        self.assertEqual(sale.transaction.type, Transaction.Type.SALE)
        self.assertEqual(get_balance(self.account), self.balance_before + D('30'))

    def test_pending_sale_can_be_edited_to_received(self):
        sale = self.sell()
        sale = save_sale(header=self.header(payment_status='received'),
                         lines=[dict(lot=self.lot1, quantity=3)], sale=sale)
        self.assertEqual(get_balance(self.account), self.balance_before + D('24'))

    def test_received_sale_cannot_go_back_to_pending(self):
        sale = self.sell(payment_status='received')
        with self.assertRaises(ValidationError):
            save_sale(header=self.header(payment_status='pending'),
                      lines=[dict(lot=self.lot1, quantity=3)], sale=sale)

    def test_save_cannot_set_refund(self):
        with self.assertRaises(ValidationError):
            self.sell(payment_status='refund')

    # ---- edit --------------------------------------------------------------

    def test_edit_replaces_lines_and_restocks(self):
        sale = self.sell()
        sale = save_sale(header=self.header(), lines=[dict(lot=self.lot1, quantity=5), dict(lot=self.lot2, quantity=1)],
                         sale=sale)
        self.assertEqual(self.remaining(self.lot1), 5)
        self.assertEqual(self.remaining(self.lot2), 3)
        self.assertEqual(sale.lines.count(), 2)
        self.assertEqual(sale.total_amount, D('55.00'))

    def test_edit_can_reuse_quantity_the_sale_already_held(self):
        sale = self.sell(lines=[dict(lot=self.lot2, quantity=4)])
        save_sale(header=self.header(), lines=[dict(lot=self.lot2, quantity=4)], sale=sale)
        self.assertEqual(self.remaining(self.lot2), 0)

    def test_edit_keeps_the_original_price_of_a_lot(self):
        sale = self.sell()
        StockLot.objects.filter(pk=self.lot1.pk).update(sale_price=D('20'))
        sale = save_sale(header=self.header(), lines=[dict(lot=self.lot1, quantity=4)], sale=sale)
        self.assertEqual(sale.lines.get().sale_price, D('8'))
        self.assertEqual(sale.total_amount, D('32.00'))

    def test_edit_of_received_sale_syncs_the_transaction(self):
        sale = self.sell(payment_status='received')
        sale = save_sale(header=self.header(payment_status='received'),
                         lines=[dict(lot=self.lot1, quantity=5)], sale=sale)
        self.assertEqual(Transaction.objects.filter(type='sale').count(), 1)
        self.assertEqual(get_balance(self.account), self.balance_before + D('40'))

    def test_edit_rolls_back_when_it_fails(self):
        sale = self.sell()
        with self.assertRaises(ValidationError):
            save_sale(header=self.header(), lines=[dict(lot=self.lot1, quantity=50)], sale=sale)
        self.assertEqual(self.remaining(self.lot1), 7)
        self.assertEqual(sale.lines.count(), 1)

    # ---- return, damaged, refund ------------------------------------------

    def test_return_puts_stock_back_in_the_same_lots(self):
        sale = self.sell(lines=[dict(lot=self.lot1, quantity=3), dict(lot=self.lot_b, quantity=2)])
        sale = return_sale(sale)
        self.assertEqual(sale.status, Sale.Status.RETURNED)
        self.assertEqual(self.remaining(self.lot1), 10)
        self.assertEqual(self.remaining(self.lot_b), 5)

    def test_returned_stock_can_be_sold_again(self):
        return_sale(self.sell(lines=[dict(lot=self.lot2, quantity=4)]))
        self.sell(lines=[dict(lot=self.lot2, quantity=4)])
        self.assertEqual(self.remaining(self.lot2), 0)

    def test_damaged_keeps_stock_deducted(self):
        sale = damage_sale(self.sell())
        self.assertEqual(sale.status, Sale.Status.DAMAGED)
        self.assertEqual(self.remaining(self.lot1), 7)

    def test_return_and_damaged_are_final(self):
        returned = return_sale(self.sell())
        damaged = damage_sale(self.sell())
        for sale in (returned, damaged):
            for action in (return_sale, damage_sale):
                with self.subTest(sale=sale.pk, action=action.__name__), self.assertRaises(ValidationError):
                    action(sale)
            with self.assertRaises(ValidationError):
                save_sale(header=self.header(), lines=[dict(lot=self.lot1, quantity=1)], sale=sale)

    def test_refund_pays_the_total_back_and_keeps_the_original_transaction(self):
        sale = self.sell(adjustments=[(self.delivery, D('6'))], payment_status='received')
        sale = refund_sale(return_sale(sale))
        self.assertEqual(sale.payment_status, Sale.PaymentStatus.REFUND)
        self.assertEqual(sale.refund_transaction.type, Transaction.Type.REFUND)
        self.assertEqual(sale.refund_transaction.amount, D('30.00'))
        self.assertEqual(sale.transaction.status, Transaction.Status.RECEIVED)
        self.assertEqual(get_balance(self.account), self.balance_before)

    def test_refund_needs_received_money_and_happens_once(self):
        with self.assertRaises(ValidationError):
            refund_sale(self.sell())
        sale = refund_sale(self.sell(payment_status='received'))
        with self.assertRaises(ValidationError):
            refund_sale(sale)

    def test_refunded_sale_cannot_be_edited(self):
        sale = refund_sale(self.sell(payment_status='received'))
        with self.assertRaises(ValidationError):
            save_sale(header=self.header(payment_status='received'),
                      lines=[dict(lot=self.lot1, quantity=1)], sale=sale)
