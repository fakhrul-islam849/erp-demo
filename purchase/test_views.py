import json
import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from payment_account.models import Account
from payment_account.services import get_balance
from product.models import Category, Product, SubCategory
from supplier.models import Supplier
from warehouse.models import Warehouse

from .models import Purchase, PurchaseAdjustmentType


TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PurchaseViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('admin1', password='pw', user_type='admin')
        cls.employee = User.objects.create_user('emp1', password='pw', user_type='employee')
        cls.account = Account.objects.create(name='Cash', opening_balance=Decimal('1000'), currency='BDT')
        cls.supplier = Supplier.objects.create(name='S1', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.supplier2 = Supplier.objects.create(name='S2', phone='01700000001', email='t@x.com', country='BD', address='a')
        cls.warehouse = Warehouse.objects.create(name='W', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        cls.p1 = Product.objects.create(subcategory=sub, name='P1')
        cls.p2 = Product.objects.create(subcategory=sub, name='P2')
        cls.delivery = PurchaseAdjustmentType.objects.create(name='Delivery', type='add')
        cls.discount = PurchaseAdjustmentType.objects.create(name='Discount', type='deduct')

    def setUp(self):
        self.client.force_login(self.admin)

    def post_data(self, payload=None, **overrides):
        data = {
            'warehouse': self.warehouse.pk, 'supplier': self.supplier.pk, 'account': self.account.pk,
            'date': date.today().isoformat(), 'status': 'paid', 'note': '',
            'payload': json.dumps(payload if payload is not None else {
                'lines': [
                    {'product': self.p1.pk, 'quantity': '10', 'purchase_price': '5', 'sale_price': '8',
                     'adjustments': [{'type': self.discount.pk, 'amount': '5'}]},
                    {'product': self.p2.pk, 'quantity': '5', 'purchase_price': '20', 'sale_price': '30',
                     'adjustments': []},
                ],
                'adjustments': [{'type': self.delivery.pk, 'amount': '30'}],
            }),
        }
        data.update(overrides)
        return data

    def create(self, **overrides):
        response = self.client.post('/purchase/add/', self.post_data(**overrides))
        return response, Purchase.objects.order_by('-id').first()

    def test_employee_forbidden(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get('/purchase/').status_code, 403)
        self.assertEqual(self.client.get('/purchase/add/').status_code, 403)

    def test_pages_render(self):
        self.assertEqual(self.client.get('/purchase/').status_code, 200)
        self.assertEqual(self.client.get('/purchase/add/').status_code, 200)

    def test_create_with_invoice_and_totals(self):
        invoice = SimpleUploadedFile('inv.pdf', b'%PDF-1.4 test', content_type='application/pdf')
        response, purchase = self.create(invoice=invoice)
        self.assertRedirects(response, f'/purchase/{purchase.pk}/')
        self.assertEqual(purchase.total_amount, Decimal('175'))
        self.assertTrue(purchase.invoice.name.endswith('.pdf'))
        self.assertEqual(get_balance(self.account), Decimal('825'))
        self.assertEqual(self.client.get(f'/purchase/{purchase.pk}/').status_code, 200)
        self.assertEqual(self.client.get(f'/purchase/{purchase.pk}/edit/').status_code, 200)

    def test_bad_invoice_extension_rejected(self):
        bad = SimpleUploadedFile('inv.exe', b'x')
        response, _ = self.create(invoice=bad)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Purchase.objects.exists())

    def test_invalid_payload_shows_errors_and_saves_nothing(self):
        payload = {'lines': [{'product': '', 'quantity': '0', 'purchase_price': 'abc', 'sale_price': '1'}],
                   'adjustments': []}
        response, _ = self.create(payload=payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Line 1: choose a product.')
        self.assertContains(response, 'quantity must be a whole number above zero')
        self.assertFalse(Purchase.objects.exists())

    def test_no_lines_rejected(self):
        response, _ = self.create(payload={'lines': [], 'adjustments': []})
        self.assertContains(response, 'Add at least one product.')

    def test_garbage_payload_does_not_crash(self):
        for raw in ('not json', '[]', '{"lines": "x"}', '{"lines": [1]}'):
            response = self.client.post('/purchase/add/', {**self.post_data(), 'payload': raw})
            self.assertEqual(response.status_code, 200)

    def test_edit_updates_purchase_and_transaction(self):
        _, purchase = self.create()
        payload = {'lines': [{'product': self.p1.pk, 'quantity': '4', 'purchase_price': '10', 'sale_price': '12'}],
                   'adjustments': []}
        response = self.client.post(f'/purchase/{purchase.pk}/edit/', self.post_data(payload=payload))
        self.assertRedirects(response, f'/purchase/{purchase.pk}/')
        purchase.refresh_from_db()
        self.assertEqual(purchase.total_amount, Decimal('40'))
        self.assertEqual(get_balance(self.account), Decimal('960'))

    def test_locked_purchase_cannot_be_edited_or_cancelled(self):
        _, purchase = self.create()
        lot = purchase.lots.first()
        lot.remaining_quantity = lot.quantity - 1
        lot.save()
        self.assertRedirects(self.client.get(f'/purchase/{purchase.pk}/edit/'), f'/purchase/{purchase.pk}/')
        self.client.post(f'/purchase/{purchase.pk}/cancel/')
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'paid')

    def test_cancel(self):
        _, purchase = self.create()
        self.client.post(f'/purchase/{purchase.pk}/cancel/')
        purchase.refresh_from_db()
        self.assertEqual(purchase.status, 'cancelled')
        self.assertEqual(get_balance(self.account), Decimal('1000'))
        self.assertRedirects(self.client.get(f'/purchase/{purchase.pk}/edit/'), f'/purchase/{purchase.pk}/')

    def test_datatable_filters(self):
        self.create()
        self.create(supplier=self.supplier2.pk, status='pending')
        base = '/purchase/datatable/?draw=1&start=0&length=10'
        self.assertEqual(self.client.get(base).json()['recordsTotal'], 2)
        self.assertEqual(self.client.get(f'{base}&status=pending').json()['recordsTotal'], 1)
        self.assertEqual(self.client.get(f'{base}&supplier={self.supplier2.pk}').json()['recordsTotal'], 1)
        self.assertEqual(self.client.get(f'{base}&date_from=2999-01-01').json()['recordsTotal'], 0)
        self.assertEqual(self.client.get(f'{base}&supplier=abc&warehouse=;&status=zzz').json()['recordsTotal'], 2)

    def test_suggest_price_prefers_same_supplier(self):
        self.assertIsNone(self.client.get(f'/purchase/suggest-price/?product={self.p1.pk}').json()['purchase_price'])
        self.create()  # p1 from supplier 1 at 5 / 8
        payload = {'lines': [{'product': self.p1.pk, 'quantity': '1', 'purchase_price': '7', 'sale_price': '9'}],
                   'adjustments': []}
        self.create(payload=payload, supplier=self.supplier2.pk)  # p1 from supplier 2 at 7 / 9

        for_s1 = self.client.get(f'/purchase/suggest-price/?product={self.p1.pk}&supplier={self.supplier.pk}').json()
        self.assertEqual((for_s1['purchase_price'], for_s1['source']), ('5.00', 'supplier'))
        for_none = self.client.get(f'/purchase/suggest-price/?product={self.p1.pk}').json()
        self.assertEqual((for_none['purchase_price'], for_none['source']), ('7.00', 'product'))

    def test_used_warehouse_and_supplier_survive_delete(self):
        self.create()
        for url in (f'/warehouse/{self.warehouse.pk}/delete/', f'/supplier/{self.supplier.pk}/delete/'):
            response = self.client.post(url, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'still reference this record')
        self.assertTrue(type(self.warehouse).objects.filter(pk=self.warehouse.pk).exists())
        self.assertTrue(type(self.supplier).objects.filter(pk=self.supplier.pk).exists())

    def test_unused_warehouse_and_supplier_can_be_deleted(self):
        self.client.post(f'/warehouse/{self.warehouse.pk}/delete/')
        self.client.post(f'/supplier/{self.supplier2.pk}/delete/')
        self.assertFalse(type(self.warehouse).objects.filter(pk=self.warehouse.pk).exists())
        self.assertFalse(type(self.supplier2).objects.filter(pk=self.supplier2.pk).exists())

    def test_used_product_and_account_survive_delete(self):
        self.create()
        for url in (f'/product/{self.p1.pk}/delete/', f'/accounts-management/{self.account.pk}/delete/'):
            response = self.client.post(url, follow=True)
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, 'still reference this record')
        self.assertTrue(type(self.p1).objects.filter(pk=self.p1.pk).exists())
        self.assertTrue(type(self.account).objects.filter(pk=self.account.pk).exists())

    def test_suggest_price_ignores_transfer_lots(self):
        from transfer.models import Transfer

        _, purchase = self.create()
        source = purchase.lots.get(product=self.p1)
        wh2 = Warehouse.objects.create(name='W2', marketplace_name='m', marketplace_location='l')
        transfer = Transfer.objects.create(
            from_warehouse=self.warehouse, to_warehouse=wh2, date=date.today(), status='confirmed',
        )
        type(source).objects.create(
            transfer=transfer, source_lot=source, product=self.p1, quantity=2, remaining_quantity=2,
            purchase_price=Decimal('99.1234'), sale_price=Decimal('120'),
        )
        data = self.client.get(f'/purchase/suggest-price/?product={self.p1.pk}').json()
        self.assertEqual(data['purchase_price'], '5.00')
