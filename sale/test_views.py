import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from payment_account.models import Account, Transaction
from product.models import Category, Product, SubCategory
from purchase.services import save_purchase
from supplier.models import Supplier
from warehouse.models import Warehouse

from .forms import parse_sale_payload
from .models import Sale, SaleAdjustmentType
from .services import save_sale

D = Decimal


class SaleViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('admin1', password='pw', user_type='admin')
        cls.employee = User.objects.create_user('emp1', password='pw', user_type='employee')
        cls.account = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.wh_a = Warehouse.objects.create(name='Alpha', marketplace_name='m', marketplace_location='l')
        cls.wh_b = Warehouse.objects.create(name='Beta', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        cls.apple = Product.objects.create(subcategory=sub, name='Apple')
        cls.pear = Product.objects.create(subcategory=sub, name='Pear')
        cls.delivery = SaleAdjustmentType.objects.create(name='Delivery', type='add')
        cls.discount = SaleAdjustmentType.objects.create(name='Discount', type='deduct')

        def buy(warehouse, product, qty, sale_price):
            return save_purchase(
                header=dict(warehouse=warehouse, supplier=supplier, account=cls.account,
                            date=date.today(), status='paid', note=''),
                lines=[dict(product=product, quantity=qty, purchase_price=D('5'), sale_price=D(sale_price))],
            ).lots.get()

        cls.apple_a = buy(cls.wh_a, cls.apple, 10, '8')
        cls.pear_b = buy(cls.wh_b, cls.pear, 4, '15')

    def setUp(self):
        self.client.force_login(self.admin)

    def make_sale(self, **header):
        return save_sale(
            header=dict(account=self.account, date=date.today(), details='', **header),
            lines=[dict(lot=self.apple_a, quantity=3)],
        )

    def payload(self, **kw):
        data = {'lines': [{'lot': self.apple_a.pk, 'quantity': 2, 'adjustments': []}], 'adjustments': []}
        data.update(kw)
        return json.dumps(data)

    def post_form(self, url, payload=None, **fields):
        data = dict(account=self.account.pk, date='2026-11-05', payment_status='pending', details='',
                    payload=payload or self.payload())
        data.update(fields)
        return self.client.post(url, data)

    # ---- access ------------------------------------------------------------

    def test_employee_and_anonymous_are_kept_out(self):
        sale = self.make_sale()
        urls = [reverse('sale:sale_datatable'), reverse('sale:available_lots'), reverse('sale:sale_add'),
                reverse('sale:sale_return', args=[sale.pk])]
        self.client.force_login(self.employee)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)

    # ---- lot search --------------------------------------------------------

    def test_lot_search_spans_warehouses_and_shows_details(self):
        rows = {r['product']: r for r in self.client.get(reverse('sale:available_lots')).json()['lots']}
        self.assertEqual(set(rows), {'Apple', 'Pear'})
        apple = rows['Apple']
        self.assertEqual(apple['warehouse'], 'Alpha')
        self.assertEqual((apple['purchase_price'], apple['sale_price'], apple['remaining']), ('5.0000', '8.00', 10))
        self.assertEqual(apple['date'], date.today().strftime('%Y-%m-%d'))

    def test_lot_search_filters_by_product_name(self):
        data = self.client.get(reverse('sale:available_lots'), {'q': 'pea'}).json()
        self.assertEqual([r['product'] for r in data['lots']], ['Pear'])

    def test_sold_out_lot_is_hidden_but_shown_for_its_own_sale(self):
        sale = save_sale(
            header=dict(account=self.account, date=date.today(), details=''),
            lines=[dict(lot=self.pear_b, quantity=4)],
        )
        url = reverse('sale:available_lots')
        names = [r['product'] for r in self.client.get(url).json()['lots']]
        self.assertNotIn('Pear', names)
        mine = self.client.get(url, {'sale': sale.pk}).json()['lots']
        pear = next(r for r in mine if r['product'] == 'Pear')
        self.assertEqual(pear['remaining'], 4)

    # ---- datatable ---------------------------------------------------------

    def test_datatable_lists_and_filters_sales(self):
        self.make_sale()
        sold = self.make_sale()
        from .services import return_sale
        return_sale(sold)
        url = reverse('sale:sale_datatable')
        self.assertEqual(self.client.get(url, {'draw': 1}).json()['recordsTotal'], 2)
        filtered = self.client.get(url, {'draw': 1, 'status': 'returned'}).json()
        self.assertEqual(len(filtered['data']), 1)

    # ---- payload parsing ---------------------------------------------------

    def test_parse_payload_ignores_a_price_sent_by_the_browser(self):
        raw = self.payload(lines=[{'lot': self.apple_a.pk, 'quantity': 2, 'sale_price': '1', 'adjustments': []}])
        lines, adjustments, errors = parse_sale_payload(raw)
        self.assertEqual(errors, [])
        self.assertNotIn('sale_price', lines[0])

    def test_parse_payload_reports_problems(self):
        for raw in ('not json', '[]', json.dumps({'lines': []}),
                    json.dumps({'lines': [{'lot': 999999, 'quantity': 1}]}),
                    json.dumps({'lines': [{'lot': self.apple_a.pk, 'quantity': 'x'}]}),
                    json.dumps({'lines': [{'lot': self.apple_a.pk, 'quantity': 1,
                                           'adjustments': [{'type': 999999, 'amount': '1'}]}]})):
            with self.subTest(raw=raw):
                self.assertTrue(parse_sale_payload(raw)[2])

    # ---- create / edit through the form -----------------------------------

    def test_post_creates_a_sale(self):
        payload = self.payload(
            lines=[{'lot': self.apple_a.pk, 'quantity': 2,
                    'adjustments': [{'type': self.delivery.pk, 'amount': '1'}]}],
            adjustments=[{'type': self.discount.pk, 'amount': '2'}],
        )
        response = self.post_form(reverse('sale:sale_add'), payload, payment_status='received')
        sale = Sale.objects.get()
        self.assertRedirects(response, reverse('sale:sale_detail', args=[sale.pk]), fetch_redirect_response=False)
        self.assertEqual(sale.total_amount, D('15.00'))
        self.assertEqual(sale.transaction.amount, D('15.00'))
        self.apple_a.refresh_from_db()
        self.assertEqual(self.apple_a.remaining_quantity, 8)

    def test_post_with_too_much_quantity_does_not_save(self):
        payload = self.payload(lines=[{'lot': self.apple_a.pk, 'quantity': 99, 'adjustments': []}])
        # re-rendering the form needs templates built in step 4, so only check nothing was saved
        try:
            self.post_form(reverse('sale:sale_add'), payload)
        except Exception:
            pass
        self.assertEqual(Sale.objects.count(), 0)
        self.apple_a.refresh_from_db()
        self.assertEqual(self.apple_a.remaining_quantity, 10)

    def test_edit_redirects_when_sale_is_not_editable(self):
        sale = self.make_sale()
        self.client.post(reverse('sale:sale_return', args=[sale.pk]))
        response = self.client.get(reverse('sale:sale_edit', args=[sale.pk]))
        self.assertRedirects(response, reverse('sale:sale_detail', args=[sale.pk]), fetch_redirect_response=False)

    # ---- actions -----------------------------------------------------------

    def test_return_damage_and_refund_actions(self):
        returned = self.make_sale(payment_status='received')
        self.client.post(reverse('sale:sale_return', args=[returned.pk]))
        self.client.post(reverse('sale:sale_refund', args=[returned.pk]))
        returned.refresh_from_db()
        self.assertEqual((returned.status, returned.payment_status), ('returned', 'refund'))
        self.assertEqual(Transaction.objects.filter(type='refund').count(), 1)

        damaged = self.make_sale()
        self.client.post(reverse('sale:sale_damage', args=[damaged.pk]))
        damaged.refresh_from_db()
        self.assertEqual(damaged.status, 'damaged')

    def test_actions_reject_get_and_invalid_state(self):
        sale = self.make_sale()
        self.assertEqual(self.client.get(reverse('sale:sale_return', args=[sale.pk])).status_code, 405)
        self.client.post(reverse('sale:sale_refund', args=[sale.pk]))  # money not received yet
        sale.refresh_from_db()
        self.assertEqual(sale.payment_status, 'pending')

    # ---- adjustment types --------------------------------------------------

    def test_adjustment_type_crud(self):
        self.client.post(reverse('sale:adjustment_type_add'), {'name': 'Packaging', 'type': 'add'})
        packaging = SaleAdjustmentType.objects.get(name='Packaging')
        duplicate = self.client.post(reverse('sale:adjustment_type_add'), {'name': 'packaging', 'type': 'add'})
        self.assertEqual(SaleAdjustmentType.objects.filter(name__iexact='packaging').count(), 1)
        self.assertNotEqual(duplicate.status_code, 302)
        self.client.post(reverse('sale:adjustment_type_edit', args=[packaging.pk]), {'name': 'Pack', 'type': 'add'})
        packaging.refresh_from_db()
        self.assertEqual(packaging.name, 'Pack')
        self.client.post(reverse('sale:adjustment_type_delete', args=[packaging.pk]))
        self.assertFalse(SaleAdjustmentType.objects.filter(pk=packaging.pk).exists())

    def test_used_adjustment_type_cannot_be_deleted(self):
        save_sale(
            header=dict(account=self.account, date=date.today(), details=''),
            lines=[dict(lot=self.apple_a, quantity=1)],
            adjustments=[(self.delivery, D('1'))],
        )
        self.client.post(reverse('sale:adjustment_type_delete', args=[self.delivery.pk]))
        self.assertTrue(SaleAdjustmentType.objects.filter(pk=self.delivery.pk).exists())

    # ---- pages render ------------------------------------------------------

    def test_pages_render(self):
        sale = self.make_sale(payment_status='received')
        for name, args in (
            ('sale:sale_list', []), ('sale:sale_add', []), ('sale:sale_detail', [sale.pk]),
            ('sale:sale_edit', [sale.pk]), ('sale:adjustment_type_list', []),
            ('sale:adjustment_type_add', []), ('sale:adjustment_type_edit', [self.delivery.pk]),
        ):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_failed_post_shows_the_form_again_with_errors(self):
        payload = self.payload(lines=[{'lot': self.apple_a.pk, 'quantity': 99, 'adjustments': []}])
        response = self.post_form(reverse('sale:sale_add'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'only 10 left')
        self.assertEqual(Sale.objects.count(), 0)

    def test_detail_shows_actions_by_state(self):
        sale = self.make_sale(payment_status='received')
        page = self.client.get(reverse('sale:sale_detail', args=[sale.pk])).content.decode()
        for url in ('sale_return', 'sale_damage', 'sale_refund', 'sale_edit'):
            self.assertIn(reverse(f'sale:{url}', args=[sale.pk]), page)
        self.client.post(reverse('sale:sale_return', args=[sale.pk]))
        page = self.client.get(reverse('sale:sale_detail', args=[sale.pk])).content.decode()
        self.assertNotIn(reverse('sale:sale_return', args=[sale.pk]), page)
        self.assertNotIn(reverse('sale:sale_edit', args=[sale.pk]), page)
        self.assertIn(reverse('sale:sale_refund', args=[sale.pk]), page)
