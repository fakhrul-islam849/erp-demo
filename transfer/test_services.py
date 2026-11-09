from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from payment_account.models import Account
from payment_account.services import get_balance
from product.models import Category, Product, SubCategory
from purchase.models import PurchaseAdjustmentType, StockLot
from purchase.services import cancel_purchase, is_locked, save_purchase
from supplier.models import Supplier
from warehouse.models import Warehouse

from .models import Transfer
from .services import cancel_transfer, confirm_transfer, save_transfer

D = Decimal


class TransferServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        cls.supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.wh_a = Warehouse.objects.create(name='A', marketplace_name='m', marketplace_location='l')
        cls.wh_b = Warehouse.objects.create(name='B', marketplace_name='m', marketplace_location='l')
        cls.wh_c = Warehouse.objects.create(name='C', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        cls.p1 = Product.objects.create(subcategory=sub, name='P1')
        cls.p2 = Product.objects.create(subcategory=sub, name='P2')
        cls.cost = PurchaseAdjustmentType.objects.create(name='Packing', type='add')
        cls.discount = PurchaseAdjustmentType.objects.create(name='Marketplace discount', type='deduct')

    def setUp(self):
        # warehouse A holds 10 x P1 landed at 5.00 and 4 x P2 landed at 10.00 (account: 1000 - 90)
        self.purchase = save_purchase(
            header=dict(
                warehouse=self.wh_a, supplier=self.supplier, account=self.account,
                date=date.today(), status='paid', note='',
            ),
            lines=[
                dict(product=self.p1, quantity=10, purchase_price=D('5'), sale_price=D('8')),
                dict(product=self.p2, quantity=4, purchase_price=D('10'), sale_price=D('15')),
            ],
        )
        self.lot1, self.lot2 = self.purchase.lots.order_by('id')

    def header(self, **kw):
        values = dict(from_warehouse=self.wh_a, to_warehouse=self.wh_b, date=date.today(), note='', account=None)
        values.update(kw)
        return values

    def line(self, lot, qty, sale='9', **kw):
        return dict(source_lot=lot, quantity=qty, sale_price=D(sale), **kw)

    def remaining(self, lot):
        lot.refresh_from_db()
        return lot.remaining_quantity

    def send_with_cost(self, qty=3, cost='15', **kw):
        return save_transfer(
            header=self.header(account=self.account), lines=[self.line(self.lot1, qty)],
            adjustments=[(self.cost, D(cost))], **kw,
        )

    # --- sending
    def test_send_reserves_stock_and_creates_unavailable_lot(self):
        transfer = save_transfer(header=self.header(), lines=[self.line(self.lot1, 4, sale='9')])

        self.assertEqual(transfer.status, 'in_transit')
        self.assertEqual(self.remaining(self.lot1), 6)
        lot = transfer.lots.get()
        self.assertEqual((lot.quantity, lot.remaining_quantity, lot.source_lot), (4, 4, self.lot1))
        self.assertEqual((lot.purchase_price, lot.landed_cost, lot.sale_price), (D('5'), D('5'), D('9')))
        self.assertEqual(lot.warehouse, self.wh_b)
        self.assertFalse(StockLot.objects.available(self.wh_b).exists())
        self.assertIsNone(transfer.transaction)
        self.assertEqual(get_balance(self.account), D('910'))

    def test_costs_and_discounts_set_the_new_landed_cost(self):
        transfer = save_transfer(
            header=self.header(account=self.account),
            lines=[
                self.line(self.lot1, 2, adjustments=[(self.discount, D('2'))]),  # value 10 - 2 = 8
                self.line(self.lot2, 1),                                           # value 10
            ],
            adjustments=[(self.cost, D('10'))],  # split by value 8 : 10 -> 4.44 / 5.56
        )
        new1, new2 = transfer.lots.order_by('id')
        self.assertEqual(new1.landed_cost, D('6.2200'))   # (8 + 4.44) / 2
        self.assertEqual(new2.landed_cost, D('15.5600'))  # (10 + 5.56) / 1
        self.assertEqual(
            (transfer.subtotal, transfer.total_cost, transfer.total_discount, transfer.net_cost),
            (D('20'), D('10'), D('2'), D('8')),
        )
        self.assertEqual((transfer.transaction.type, transfer.transaction.status), ('transfer', 'pending'))
        self.assertEqual(transfer.transaction.amount, D('8'))

    # --- the account
    def test_cost_is_paid_only_when_confirmed(self):
        transfer = self.send_with_cost()
        self.assertEqual(transfer.lots.get().landed_cost, D('10.0000'))  # (3 x 5 + 15) / 3
        self.assertEqual(get_balance(self.account), D('910'))  # pending

        confirm_transfer(transfer)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'confirmed')
        self.assertIsNotNone(transfer.confirmed_at)
        self.assertEqual(transfer.transaction.status, 'paid')
        self.assertEqual(get_balance(self.account), D('895'))
        self.assertEqual(list(StockLot.objects.available(self.wh_b)), [transfer.lots.get()])

    def test_transfer_without_cost_has_no_transaction(self):
        transfer = save_transfer(header=self.header(), lines=[self.line(self.lot1, 1)])
        confirm_transfer(transfer)
        transfer.refresh_from_db()
        self.assertIsNone(transfer.transaction)
        self.assertEqual(get_balance(self.account), D('910'))

    # --- editing
    def test_edit_in_transit_replaces_lines_and_updates_the_transaction(self):
        transfer = self.send_with_cost(qty=4, cost='8')
        transaction_id = transfer.transaction_id
        self.assertEqual(self.remaining(self.lot1), 6)

        transfer = save_transfer(
            transfer=transfer, header=self.header(account=self.account),
            lines=[self.line(self.lot1, 2)], adjustments=[(self.cost, D('6'))],
        )
        self.assertEqual(self.remaining(self.lot1), 8)
        self.assertEqual(transfer.lots.count(), 1)
        self.assertEqual(transfer.lots.get().quantity, 2)
        self.assertEqual(transfer.transaction_id, transaction_id)
        self.assertEqual(transfer.transaction.amount, D('6'))

        transfer = save_transfer(transfer=transfer, header=self.header(), lines=[self.line(self.lot1, 2)])
        transfer.transaction.refresh_from_db()
        self.assertEqual((transfer.transaction.status, transfer.transaction.amount), ('cancelled', D('0')))
        self.assertEqual(get_balance(self.account), D('910'))

    def test_edit_can_move_stock_to_another_lot(self):
        transfer = save_transfer(header=self.header(), lines=[self.line(self.lot1, 4)])
        save_transfer(transfer=transfer, header=self.header(), lines=[self.line(self.lot2, 3)])
        self.assertEqual(self.remaining(self.lot1), 10)
        self.assertEqual(self.remaining(self.lot2), 1)

    # --- cancelling
    def test_cancel_in_transit_returns_stock_and_cancels_the_cost(self):
        transfer = self.send_with_cost()
        cancel_transfer(transfer)
        transfer.refresh_from_db()

        self.assertEqual(transfer.status, 'cancelled')
        self.assertEqual(self.remaining(self.lot1), 10)
        self.assertEqual(transfer.transaction.status, 'cancelled')
        self.assertEqual(get_balance(self.account), D('910'))
        self.assertEqual(transfer.lots.count(), 1)  # kept for the record
        self.assertFalse(StockLot.objects.available(self.wh_b).exists())

        cancel_transfer(transfer)  # cancelling again changes nothing
        self.assertEqual(self.remaining(self.lot1), 10)
        with self.assertRaises(ValidationError):
            confirm_transfer(transfer)
        with self.assertRaises(ValidationError):
            save_transfer(transfer=transfer, header=self.header(), lines=[self.line(self.lot1, 1)])

    def test_confirmed_transfer_is_final(self):
        transfer = self.send_with_cost()
        confirm_transfer(transfer)
        with self.assertRaises(ValidationError):
            cancel_transfer(transfer)
        with self.assertRaises(ValidationError):
            confirm_transfer(transfer)
        with self.assertRaises(ValidationError):
            save_transfer(transfer=transfer, header=self.header(), lines=[self.line(self.lot1, 1)])
        self.assertEqual(self.remaining(self.lot1), 7)

    # --- rules
    def assertInvalid(self, **kwargs):
        with self.assertRaises(ValidationError):
            save_transfer(**kwargs)
        self.assertFalse(Transfer.objects.exists())
        self.assertEqual(self.remaining(self.lot1), 10)
        self.assertEqual(self.remaining(self.lot2), 4)

    def test_input_rules(self):
        line = self.line(self.lot1, 1)
        self.assertInvalid(header=self.header(to_warehouse=self.wh_a), lines=[line])
        self.assertInvalid(header=self.header(), lines=[])
        self.assertInvalid(header=self.header(), lines=[self.line(self.lot1, 0)])
        self.assertInvalid(header=self.header(), lines=[self.line(self.lot1, 1), self.line(self.lot1, 2)])
        self.assertInvalid(header=self.header(), lines=[self.line(self.lot1, 1, sale='-1')])
        self.assertInvalid(
            header=self.header(account=self.account), lines=[line], adjustments=[(self.cost, D('0'))],
        )

    def test_cost_needs_an_account(self):
        self.assertInvalid(header=self.header(), lines=[self.line(self.lot1, 1)], adjustments=[(self.cost, D('5'))])

    def test_discount_cannot_exceed_costs(self):
        self.assertInvalid(
            header=self.header(account=self.account), lines=[self.line(self.lot1, 1)],
            adjustments=[(self.cost, D('3')), (self.discount, D('5'))],
        )

    def test_cannot_move_more_than_is_left(self):
        self.assertInvalid(header=self.header(), lines=[self.line(self.lot1, 11)])

    def test_lot_must_be_available_in_the_from_warehouse(self):
        self.assertInvalid(header=self.header(from_warehouse=self.wh_b, to_warehouse=self.wh_a), lines=[self.line(self.lot1, 1)])

    def test_stock_of_a_cancelled_purchase_cannot_move(self):
        cancel_purchase(self.purchase)
        self.assertInvalid(header=self.header(), lines=[self.line(self.lot1, 1)])

    def test_stock_in_transit_cannot_move_again(self):
        transfer = save_transfer(header=self.header(), lines=[self.line(self.lot1, 4)])
        in_transit = transfer.lots.get()
        with self.assertRaises(ValidationError):
            save_transfer(
                header=self.header(from_warehouse=self.wh_b, to_warehouse=self.wh_c),
                lines=[self.line(in_transit, 1)],
            )

    def test_one_bad_line_rolls_everything_back(self):
        self.assertInvalid(header=self.header(), lines=[self.line(self.lot1, 3), self.line(self.lot2, 99)])

    # --- chains and the source purchase
    def test_a_confirmed_lot_can_move_on_and_keeps_its_cost(self):
        first = self.send_with_cost()  # 3 x P1 landed at 10.0000 in B
        confirm_transfer(first)
        in_b = first.lots.get()

        second = save_transfer(
            header=self.header(from_warehouse=self.wh_b, to_warehouse=self.wh_c, account=self.account),
            lines=[self.line(in_b, 2, sale='20')],
            adjustments=[(self.cost, D('6'))],
        )
        in_c = second.lots.get()
        self.assertEqual(in_c.purchase_price, D('10.0000'))
        self.assertEqual(in_c.landed_cost, D('13.0000'))  # (2 x 10 + 6) / 2
        self.assertEqual((in_c.source_lot, in_c.sale_price, in_c.warehouse), (in_b, D('20'), self.wh_c))
        self.assertEqual(self.remaining(in_b), 1)

    def test_source_purchase_is_locked_while_stock_is_in_transit(self):
        transfer = save_transfer(header=self.header(), lines=[self.line(self.lot1, 4)])
        self.assertTrue(is_locked(self.purchase))
        with self.assertRaises(ValidationError):
            cancel_purchase(self.purchase)
        cancel_transfer(transfer)
        self.assertFalse(is_locked(self.purchase))
