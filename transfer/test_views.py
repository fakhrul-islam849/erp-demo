import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from payment_account.models import Account
from payment_account.services import get_balance
from product.models import Category, Product, SubCategory
from purchase.models import PurchaseAdjustmentType
from purchase.services import save_purchase
from supplier.models import Supplier
from warehouse.models import Warehouse

from .models import Transfer
from .services import cancel_transfer, confirm_transfer, save_transfer

D = Decimal


class TransferViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('admin1', password='pw', user_type='admin')
        cls.employee = User.objects.create_user('emp1', password='pw', user_type='employee')
        cls.account = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.wh_a = Warehouse.objects.create(name='A', marketplace_name='m', marketplace_location='l')
        cls.wh_b = Warehouse.objects.create(name='B', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        cls.p1 = Product.objects.create(subcategory=sub, name='Apple')
        cls.p2 = Product.objects.create(subcategory=sub, name='Pear')
        cls.cost = PurchaseAdjustmentType.objects.create(name='Packing', type='add')
        cls.discount = PurchaseAdjustmentType.objects.create(name='Marketplace discount', type='deduct')
        purchase = save_purchase(
            header=dict(warehouse=cls.wh_a, supplier=supplier, account=cls.account,
                        date=date.today(), status='paid', note=''),
            lines=[
                dict(product=cls.p1, quantity=10, purchase_price=D('5'), sale_price=D('8')),
                dict(product=cls.p2, quantity=4, purchase_price=D('10'), sale_price=D('15')),
            ],
        )
        cls.lot1, cls.lot2 = purchase.lots.order_by('id')

    def setUp(self):
        self.client.force_login(self.admin)

    def post_data(self, payload=None, **overrides):
        data = {
            'from_warehouse': self.wh_a.pk, 'to_warehouse': self.wh_b.pk, 'date': date.today().isoformat(),
            'account': self.account.pk, 'note': '',
            'payload': json.dumps(payload if payload is not None else {
                'lines': [{'source_lot': self.lot1.pk, 'quantity': '3', 'sale_price': '9', 'adjustments': []}],
                'adjustments': [{'type': self.cost.pk, 'amount': '15'}],
            }),
        }
        data.update(overrides)
        return data

    def send(self, **overrides):
        response = self.client.post('/transfer/add/', self.post_data(**overrides))
        return response, Transfer.objects.order_by('-id').first()

    def remaining(self, lot):
        lot.refresh_from_db()
        return lot.remaining_quantity

    # --- access and pages
    def test_employee_forbidden(self):
        self.client.force_login(self.employee)
        for url in ('/transfer/', '/transfer/add/', f'/transfer/lots/?warehouse={self.wh_a.pk}'):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_pages_render(self):
        _, transfer = self.send()
        for url in ('/transfer/', '/transfer/add/', f'/transfer/{transfer.pk}/', f'/transfer/{transfer.pk}/edit/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    # --- available stock
    def test_lots_endpoint_lists_available_stock(self):
        data = self.client.get(f'/transfer/lots/?warehouse={self.wh_a.pk}').json()['lots']
        self.assertEqual([(l['product'], l['remaining']) for l in data], [('Apple', 10), ('Pear', 4)])
        self.assertEqual(data[0]['landed_cost'], '5.0000')
        self.assertEqual(self.client.get(f'/transfer/lots/?warehouse={self.wh_b.pk}').json()['lots'], [])
        self.assertEqual(self.client.get('/transfer/lots/').json()['lots'], [])

    def test_lots_endpoint_adds_back_reserved_stock_when_editing(self):
        _, transfer = self.send(payload={
            'lines': [{'source_lot': self.lot2.pk, 'quantity': '4', 'sale_price': '9', 'adjustments': []}],
            'adjustments': [],
        })
        self.assertEqual(self.remaining(self.lot2), 0)
        plain = self.client.get(f'/transfer/lots/?warehouse={self.wh_a.pk}').json()['lots']
        self.assertEqual([l['product'] for l in plain], ['Apple'])  # Pear is fully reserved

        editing = self.client.get(f'/transfer/lots/?warehouse={self.wh_a.pk}&transfer={transfer.pk}').json()['lots']
        self.assertEqual([(l['product'], l['remaining']) for l in editing], [('Apple', 10), ('Pear', 4)])

    # --- send, edit, confirm, cancel
    def test_send_creates_an_in_transit_transfer(self):
        response, transfer = self.send()
        self.assertRedirects(response, f'/transfer/{transfer.pk}/')
        self.assertEqual(transfer.status, 'in_transit')
        self.assertEqual(self.remaining(self.lot1), 7)
        self.assertEqual(transfer.net_cost, D('15'))
        self.assertEqual(transfer.transaction.status, 'pending')
        self.assertEqual(get_balance(self.account), D('910'))

    def test_invalid_input_shows_errors_and_saves_nothing(self):
        payload = {'lines': [{'source_lot': '', 'quantity': '0', 'sale_price': 'abc'}], 'adjustments': []}
        response, _ = self.send(payload=payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Line 1: choose a product.')
        self.assertContains(response, 'quantity must be a whole number above zero')
        self.assertFalse(Transfer.objects.exists())

    def test_service_errors_are_shown(self):
        payload = {'lines': [{'source_lot': self.lot1.pk, 'quantity': '99', 'sale_price': '9', 'adjustments': []}],
                   'adjustments': []}
        response, _ = self.send(payload=payload)
        self.assertContains(response, 'only 10 left')
        self.assertEqual(self.remaining(self.lot1), 10)

    def test_cost_without_account_is_refused(self):
        response, _ = self.send(account='')
        self.assertContains(response, 'Choose the account that pays the transfer cost.')
        self.assertFalse(Transfer.objects.exists())

    def test_same_warehouse_is_refused(self):
        response, _ = self.send(to_warehouse=self.wh_a.pk)
        self.assertContains(response, 'Choose a different warehouse')
        self.assertFalse(Transfer.objects.exists())

    def test_garbage_payload_does_not_crash(self):
        for raw in ('not json', '[]', '{"lines": "x"}', '{"lines": [1]}', 'null'):
            response = self.client.post('/transfer/add/', {**self.post_data(), 'payload': raw})
            self.assertEqual(response.status_code, 200, raw)

    def test_edit_changes_the_transfer(self):
        _, transfer = self.send()
        payload = {'lines': [{'source_lot': self.lot1.pk, 'quantity': '5', 'sale_price': '12', 'adjustments': []}],
                   'adjustments': []}
        response = self.client.post(f'/transfer/{transfer.pk}/edit/', self.post_data(payload=payload))
        self.assertRedirects(response, f'/transfer/{transfer.pk}/')
        transfer.refresh_from_db()
        self.assertEqual(self.remaining(self.lot1), 5)
        self.assertEqual(transfer.net_cost, D('0'))
        self.assertEqual(transfer.transaction.status, 'cancelled')

    def test_confirm_makes_stock_available_and_pays_the_cost(self):
        _, transfer = self.send()
        response = self.client.post(f'/transfer/{transfer.pk}/confirm/')
        self.assertRedirects(response, f'/transfer/{transfer.pk}/')
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'confirmed')
        self.assertEqual(get_balance(self.account), D('895'))
        lots = self.client.get(f'/transfer/lots/?warehouse={self.wh_b.pk}').json()['lots']
        self.assertEqual([(l['product'], l['remaining'], l['landed_cost']) for l in lots], [('Apple', 3, '10.0000')])

        # final: no more edits, confirms or cancels
        self.assertRedirects(self.client.get(f'/transfer/{transfer.pk}/edit/'), f'/transfer/{transfer.pk}/')
        self.client.post(f'/transfer/{transfer.pk}/cancel/')
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'confirmed')

    def test_cancel_returns_stock(self):
        _, transfer = self.send()
        self.client.post(f'/transfer/{transfer.pk}/cancel/')
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'cancelled')
        self.assertEqual(self.remaining(self.lot1), 10)
        self.assertEqual(get_balance(self.account), D('910'))
        self.assertRedirects(self.client.get(f'/transfer/{transfer.pk}/edit/'), f'/transfer/{transfer.pk}/')

    def test_actions_need_post(self):
        _, transfer = self.send()
        self.assertEqual(self.client.get(f'/transfer/{transfer.pk}/confirm/').status_code, 405)
        self.assertEqual(self.client.get(f'/transfer/{transfer.pk}/cancel/').status_code, 405)

    # --- list
    def test_datatable_filters(self):
        self.send()
        self.send(payload={
            'lines': [{'source_lot': self.lot2.pk, 'quantity': '1', 'sale_price': '9', 'adjustments': []}],
            'adjustments': [],
        })
        confirm_transfer(Transfer.objects.order_by('id').first())
        base = '/transfer/datatable/?draw=1&start=0&length=10'
        self.assertEqual(self.client.get(base).json()['recordsTotal'], 2)
        self.assertEqual(self.client.get(f'{base}&status=confirmed').json()['recordsTotal'], 1)
        self.assertEqual(self.client.get(f'{base}&from_warehouse={self.wh_b.pk}').json()['recordsTotal'], 0)
        self.assertEqual(self.client.get(f'{base}&to_warehouse={self.wh_b.pk}').json()['recordsTotal'], 2)
        self.assertEqual(self.client.get(f'{base}&date_from=2999-01-01').json()['recordsTotal'], 0)
        self.assertEqual(self.client.get(f'{base}&from_warehouse=abc&status=zzz&date_to=x').json()['recordsTotal'], 2)
        row = self.client.get(f'{base}&status=confirmed').json()['data'][0]
        self.assertEqual(row['net_cost'], '15.00 BDT')

    # --- protection
    def test_warehouse_with_transfers_cannot_be_deleted(self):
        self.send()
        response = self.client.post(f'/warehouse/{self.wh_b.pk}/delete/', follow=True)
        self.assertContains(response, 'still reference this record')
        self.assertTrue(Warehouse.objects.filter(pk=self.wh_b.pk).exists())


class AvailableLotsSearchTests(TestCase):
    """The stock dropdown never loads everything: ten random lots, then search by product name."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user('admin1', password='pw', user_type='admin')
        cls.account = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        supplier = Supplier.objects.create(name='S', phone='01700000000', email='s@x.com', country='BD', address='a')
        cls.wh_a = Warehouse.objects.create(name='A', marketplace_name='m', marketplace_location='l')
        cls.wh_b = Warehouse.objects.create(name='B', marketplace_name='m', marketplace_location='l')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        names = ['Apple', 'Pear'] + [f'Bulk {n:02d}' for n in range(1, 24)]
        products = [Product.objects.create(subcategory=sub, name=name) for name in names]
        purchase = save_purchase(
            header=dict(warehouse=cls.wh_a, supplier=supplier, account=cls.account,
                        date=date.today(), status='paid', note=''),
            lines=[dict(product=p, quantity=5, purchase_price=D('2'), sale_price=D('3')) for p in products],
        )
        cls.pear_lot = purchase.lots.get(product__name='Pear')

    def setUp(self):
        self.client.force_login(self.admin)

    def lots(self, **params):
        params = {'warehouse': self.wh_a.pk, **params}
        return self.client.get('/transfer/lots/', params).json()

    def test_ten_random_lots_without_a_term(self):
        data = self.lots()
        self.assertEqual(len(data['lots']), 10)
        self.assertFalse(data['more'])
        seen = {tuple(l['id'] for l in self.lots()['lots']) for _ in range(8)}
        self.assertGreater(len(seen), 1)

    def test_term_pages_by_product_name(self):
        pages = [self.lots(q='bulk', page=n) for n in (1, 2, 3)]
        self.assertEqual([len(p['lots']) for p in pages], [10, 10, 3])
        self.assertEqual([p['more'] for p in pages], [True, True, False])
        self.assertEqual([l['product'] for p in pages for l in p['lots']], [f'Bulk {n:02d}' for n in range(1, 24)])
        self.assertEqual([l['product'] for l in self.lots(q='APP')['lots']], ['Apple'])
        self.assertEqual(self.lots(q='nothing like this'), {'lots': [], 'more': False})

    def test_stock_of_other_warehouses_is_not_listed(self):
        self.assertEqual(self.client.get(f'/transfer/lots/?warehouse={self.wh_b.pk}&q=a').json()['lots'], [])

    def test_editing_still_finds_a_fully_reserved_lot_by_search(self):
        transfer = save_transfer(
            header=dict(from_warehouse=self.wh_a, to_warehouse=self.wh_b, date=date.today(), note='', account=None),
            lines=[dict(source_lot=self.pear_lot, quantity=5, sale_price=D('9'))],
        )
        self.assertEqual(self.lots(q='pear')['lots'], [])
        found = self.lots(q='pear', transfer=transfer.pk)['lots']
        self.assertEqual([(l['product'], l['remaining']) for l in found], [('Pear', 5)])

    def test_edit_page_embeds_only_the_saved_lots(self):
        transfer = save_transfer(
            header=dict(from_warehouse=self.wh_a, to_warehouse=self.wh_b, date=date.today(), note='', account=None),
            lines=[dict(source_lot=self.pear_lot, quantity=2, sale_price=D('9'))],
        )
        response = self.client.get(f'/transfer/{transfer.pk}/edit/')
        self.assertEqual([(l['id'], l['remaining']) for l in response.context['initial_lots']], [(self.pear_lot.pk, 5)])
