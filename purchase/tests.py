from django.db import IntegrityError, transaction
from django.test import TestCase

from .forms import AdjustmentTypeForm
from .models import PurchaseAdjustmentType


class AdjustmentTypeFormTests(TestCase):
    def setUp(self):
        self.delivery = PurchaseAdjustmentType.objects.create(name='Delivery', type='add')

    def test_duplicate_name_rejected_case_insensitive(self):
        form = AdjustmentTypeForm({'name': 'delivery', 'type': 'add'})
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_edit_keeps_own_name(self):
        form = AdjustmentTypeForm({'name': 'Delivery', 'type': 'deduct'}, adjustment_type=self.delivery)
        self.assertTrue(form.is_valid())
        form.save()
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.type, 'deduct')


class AdjustmentTypeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        cls.admin = User.objects.create_user('admin1', password='pw', user_type='admin')
        cls.employee = User.objects.create_user('emp1', password='pw', user_type='employee')

    def test_employee_forbidden(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get('/purchase/adjustment-types/').status_code, 403)

    def test_admin_crud_flow(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/purchase/adjustment-types/').status_code, 200)
        self.assertEqual(self.client.get('/purchase/adjustment-types/add/').status_code, 200)

        resp = self.client.post('/purchase/adjustment-types/add/', {'name': 'Delivery Cost', 'type': 'add'})
        self.assertRedirects(resp, '/purchase/adjustment-types/')
        obj = PurchaseAdjustmentType.objects.get(name='Delivery Cost')

        resp = self.client.get('/purchase/adjustment-types/datatable/?draw=1&start=0&length=10')
        self.assertEqual(resp.json()['recordsTotal'], 1)
        self.assertEqual(resp.json()['data'][0]['type'], 'Add (cost)')

        self.client.post(f'/purchase/adjustment-types/{obj.pk}/edit/', {'name': 'Delivery Cost', 'type': 'deduct'})
        obj.refresh_from_db()
        self.assertEqual(obj.type, 'deduct')

        self.client.post(f'/purchase/adjustment-types/{obj.pk}/delete/')
        self.assertFalse(PurchaseAdjustmentType.objects.exists())


class PurchaseModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import date
        from decimal import Decimal

        from payment_account.models import Account
        from product.models import Category, Product, SubCategory
        from supplier.models import Supplier
        from warehouse.models import Warehouse

        from .models import Purchase

        account = Account.objects.create(name='Cash', opening_balance=Decimal('0'), currency='BDT')
        supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        warehouse = Warehouse.objects.create(name='W', marketplace_name='m', marketplace_location='l')
        category = Category.objects.create(name='C')
        sub = SubCategory.objects.create(category=category, name='SC')
        cls.product = Product.objects.create(subcategory=sub, name='P')
        cls.purchase = Purchase.objects.create(
            warehouse=warehouse, supplier=supplier, account=account, date=date.today(),
        )
        cls.other = Purchase.objects.create(
            warehouse=warehouse, supplier=supplier, account=account, date=date.today(),
        )
        cls.adj_type = PurchaseAdjustmentType.objects.create(name='Delivery', type='add')

    def lot(self, purchase=None, **kw):
        from decimal import Decimal

        from .models import StockLot
        values = dict(
            purchase=purchase or self.purchase, product=self.product, quantity=10,
            remaining_quantity=10, purchase_price=Decimal('5'), sale_price=Decimal('8'),
        )
        values.update(kw)
        return StockLot.objects.create(**values)

    def test_remaining_cannot_exceed_quantity(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.lot(remaining_quantity=11)

    def test_quantity_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.lot(quantity=0, remaining_quantity=0)

    def test_adjustment_scope_and_cross_purchase_check(self):
        from decimal import Decimal

        from django.core.exceptions import ValidationError

        from .models import PurchaseAdjustment

        line = self.lot()
        header_adj = PurchaseAdjustment(purchase=self.purchase, adjustment_type=self.adj_type, amount=Decimal('50'))
        line_adj = PurchaseAdjustment(purchase=self.purchase, lot=line, adjustment_type=self.adj_type, amount=Decimal('5'))
        bad_adj = PurchaseAdjustment(purchase=self.other, lot=line, adjustment_type=self.adj_type, amount=Decimal('5'))
        self.assertEqual(header_adj.scope, 'purchase')
        self.assertEqual(line_adj.scope, 'line')
        line_adj.clean()
        with self.assertRaises(ValidationError):
            bad_adj.clean()

    def test_used_adjustment_type_is_protected(self):
        from decimal import Decimal

        from django.db.models import ProtectedError

        from .models import PurchaseAdjustment
        PurchaseAdjustment.objects.create(purchase=self.purchase, adjustment_type=self.adj_type, amount=Decimal('1'))
        with self.assertRaises(ProtectedError):
            self.adj_type.delete()
