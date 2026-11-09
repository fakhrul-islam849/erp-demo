from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from payment_account.models import Account, Transaction
from payment_account.services import get_balance
from product.models import Category, Product, SubCategory
from purchase.models import Purchase, PurchaseAdjustment, PurchaseAdjustmentType, StockLot
from supplier.models import Supplier
from warehouse.models import Warehouse

from .models import Transfer


class TransferFoundationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name='Cash', opening_balance=Decimal('1000'), currency='BDT')
        cls.supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.wh_a = Warehouse.objects.create(name='A', marketplace_name='m', marketplace_location='l')
        cls.wh_b = Warehouse.objects.create(name='B', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        cls.product = Product.objects.create(subcategory=sub, name='P')
        cls.adj_type = PurchaseAdjustmentType.objects.create(name='Packing', type='add')

    def purchase(self, warehouse=None, status='paid'):
        return Purchase.objects.create(
            warehouse=warehouse or self.wh_a, supplier=self.supplier, account=self.account,
            date=date.today(), status=status,
        )

    def transfer(self, status='in_transit', **kw):
        values = dict(from_warehouse=self.wh_a, to_warehouse=self.wh_b, date=date.today(), status=status)
        values.update(kw)
        return Transfer.objects.create(**values)

    def lot(self, **kw):
        values = dict(
            product=self.product, quantity=10, remaining_quantity=10,
            purchase_price=Decimal('5'), sale_price=Decimal('8'),
        )
        values.update(kw)
        return StockLot.objects.create(**values)

    def assertRejected(self, func):
        with self.assertRaises(IntegrityError), transaction.atomic():
            func()

    # --- Transfer
    def test_transfer_needs_two_different_warehouses(self):
        self.assertRejected(lambda: self.transfer(to_warehouse=self.wh_a))

    # --- StockLot ownership
    def test_lot_needs_exactly_one_owner(self):
        self.assertRejected(lambda: self.lot())  # neither
        purchase, transfer = self.purchase(), self.transfer()
        source = self.lot(purchase=purchase)
        self.assertRejected(lambda: self.lot(purchase=purchase, transfer=transfer, source_lot=source))  # both

    def test_source_lot_only_on_transfer_lots(self):
        purchase, transfer = self.purchase(), self.transfer()
        source = self.lot(purchase=purchase)
        self.assertRejected(lambda: self.lot(purchase=purchase, source_lot=source))  # source without transfer
        self.assertRejected(lambda: self.lot(transfer=transfer))  # transfer without source
        moved = self.lot(transfer=transfer, source_lot=source, quantity=3, remaining_quantity=3)
        self.assertEqual(moved.warehouse, self.wh_b)
        self.assertEqual(source.warehouse, self.wh_a)

    def test_lot_price_keeps_four_decimals(self):
        lot = self.lot(purchase=self.purchase(), purchase_price=Decimal('6.1234'))
        lot.refresh_from_db()
        self.assertEqual(lot.purchase_price, Decimal('6.1234'))

    def test_source_lot_is_protected(self):
        source = self.lot(purchase=self.purchase())
        self.lot(transfer=self.transfer(), source_lot=source, quantity=1, remaining_quantity=1)
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            source.delete()

    # --- availability
    def test_available_and_in_warehouse(self):
        paid = self.lot(purchase=self.purchase())
        cancelled = self.lot(purchase=self.purchase(status='cancelled'))
        empty = self.lot(purchase=self.purchase(), remaining_quantity=0)
        in_transit = self.lot(
            transfer=self.transfer('in_transit'), source_lot=paid, quantity=2, remaining_quantity=2,
        )
        confirmed = self.lot(
            transfer=self.transfer('confirmed'), source_lot=paid, quantity=3, remaining_quantity=3,
        )

        everywhere = set(StockLot.objects.available())
        self.assertEqual(everywhere, {paid, confirmed})
        self.assertEqual(set(StockLot.objects.available(self.wh_a)), {paid})
        self.assertEqual(set(StockLot.objects.available(self.wh_b)), {confirmed})
        self.assertEqual(set(StockLot.objects.in_warehouse(self.wh_b)), {in_transit, confirmed})
        for hidden in (cancelled, empty, in_transit):
            self.assertNotIn(hidden, everywhere)

    # --- adjustments
    def test_adjustment_needs_exactly_one_owner(self):
        purchase, transfer = self.purchase(), self.transfer()
        amount = Decimal('5')
        self.assertRejected(lambda: PurchaseAdjustment.objects.create(adjustment_type=self.adj_type, amount=amount))
        self.assertRejected(lambda: PurchaseAdjustment.objects.create(
            purchase=purchase, transfer=transfer, adjustment_type=self.adj_type, amount=amount))
        PurchaseAdjustment.objects.create(transfer=transfer, adjustment_type=self.adj_type, amount=amount)
        self.assertEqual(transfer.adjustments.count(), 1)

    def test_adjustment_clean_checks_lot_owner(self):
        purchase, transfer = self.purchase(), self.transfer()
        source = self.lot(purchase=purchase)
        moved = self.lot(transfer=transfer, source_lot=source, quantity=2, remaining_quantity=2)

        PurchaseAdjustment(transfer=transfer, lot=moved, adjustment_type=self.adj_type, amount=1).clean()
        with self.assertRaises(ValidationError):  # lot belongs to the transfer, not the purchase
            PurchaseAdjustment(purchase=purchase, lot=moved, adjustment_type=self.adj_type, amount=1).clean()
        with self.assertRaises(ValidationError):  # lot belongs to the purchase, not the transfer
            PurchaseAdjustment(transfer=transfer, lot=source, adjustment_type=self.adj_type, amount=1).clean()

    # --- transactions
    def test_transfer_cost_is_an_outflow_when_paid(self):
        def add(status):
            return Transaction.objects.create(
                account=self.account, type='transfer', status=status, amount=Decimal('40'), date=date.today())
        add('pending')
        add('cancelled')
        self.assertEqual(get_balance(self.account), Decimal('1000'))
        add('paid')
        self.assertEqual(get_balance(self.account), Decimal('960'))

    def test_transfer_transaction_cannot_be_received(self):
        self.assertRejected(lambda: Transaction.objects.create(
            account=self.account, type='transfer', status='received', amount=Decimal('1'), date=date.today()))
