from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Category, Product, SubCategory


class ProductSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('admin1', password='pw', user_type='admin')
        cls.employee = User.objects.create_user('emp1', password='pw', user_type='employee')
        sub = SubCategory.objects.create(category=Category.objects.create(name='C'), name='SC')
        Product.objects.bulk_create(Product(subcategory=sub, name=f'Item {n:02d}') for n in range(1, 24))
        Product.objects.create(subcategory=sub, name='Banana')

    def search(self, **params):
        return self.client.get('/product/search/', params).json()

    def test_employee_forbidden(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get('/product/search/').status_code, 403)

    def test_without_a_term_ten_random_products_come_back(self):
        self.client.force_login(self.admin)
        data = self.search()
        self.assertEqual(len(data['products']), 10)
        self.assertFalse(data['more'])
        names = [p['name'] for p in data['products']]
        self.assertEqual(names, sorted(names, key=str.lower))
        # random: over many calls more than one distinct set shows up
        seen = {tuple(p['id'] for p in self.search()['products']) for _ in range(8)}
        self.assertGreater(len(seen), 1)

    def test_term_filters_orders_and_pages(self):
        self.client.force_login(self.admin)
        pages = [self.search(q='item', page=n) for n in (1, 2, 3)]
        self.assertEqual([len(p['products']) for p in pages], [10, 10, 3])
        self.assertEqual([p['more'] for p in pages], [True, True, False])
        names = [p['name'] for page in pages for p in page['products']]
        self.assertEqual(names, [f'Item {n:02d}' for n in range(1, 24)])

    def test_search_is_case_insensitive_and_partial(self):
        self.client.force_login(self.admin)
        self.assertEqual([p['name'] for p in self.search(q='  ANAN ')['products']], ['Banana'])
        self.assertEqual(self.search(q='zzz'), {'products': [], 'more': False})

    def test_bad_page_falls_back_to_the_first(self):
        self.client.force_login(self.admin)
        for page in ('abc', '0', '-3', ''):
            self.assertEqual(len(self.search(q='item', page=page)['products']), 10, page)
