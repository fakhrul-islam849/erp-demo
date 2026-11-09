from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from payment_account.models import Account, Transaction
from payment_account.services import get_balance

from .forms import CategoryForm, IncomeForm
from .models import Income, IncomeCategory
from .services import save_income

D = Decimal


class IncomeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('admin1', password='pw', user_type='admin')
        cls.employee = User.objects.create_user('emp1', password='pw', user_type='employee')
        cls.cash = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        cls.bank = Account.objects.create(name='Bank', opening_balance=D('500'), currency='BDT')
        cls.interest = IncomeCategory.objects.create(name='Interest')
        cls.rent = IncomeCategory.objects.create(name='Rent')

    def setUp(self):
        self.client.force_login(self.admin)

    def make_income(self, **kw):
        values = dict(title='Savings interest', account=self.cash, category=self.interest,
                      amount=D('250'), date=date(2026, 11, 5))
        values.update(kw)
        return save_income(values=values)

    def data(self, **kw):
        data = dict(title='Rent for shop', account=self.cash.pk, category=self.rent.pk,
                    amount='300.00', date='2026-11-05')
        data.update(kw)
        return data

    # ---- access ------------------------------------------------------------

    def test_employee_and_anonymous_are_kept_out(self):
        income = self.make_income()
        urls = [reverse('income:income_datatable'), reverse('income:income_add'),
                reverse('income:category_datatable'), reverse('income:category_add'),
                reverse('income:income_delete', args=[income.pk])]
        self.client.force_login(self.employee)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)

    # ---- income ------------------------------------------------------------

    def test_post_creates_an_income_and_raises_the_balance(self):
        response = self.client.post(reverse('income:income_add'), self.data())
        self.assertRedirects(response, reverse('income:income_list'), fetch_redirect_response=False)
        income = Income.objects.get()
        self.assertEqual((income.title, income.amount, income.category), ('Rent for shop', D('300.00'), self.rent))
        self.assertEqual(get_balance(self.cash), D('1300'))

    def test_post_edits_an_income(self):
        income = self.make_income()
        self.client.post(reverse('income:income_edit', args=[income.pk]),
                         self.data(account=self.bank.pk, amount='100'))
        self.assertEqual(get_balance(self.cash), D('1000'))
        self.assertEqual(get_balance(self.bank), D('600'))
        self.assertEqual(Income.objects.count(), 1)

    def test_invalid_post_saves_nothing(self):
        for bad in (dict(amount='0'), dict(amount='-1'), dict(amount='abc'), dict(title='  '),
                    dict(category=''), dict(account=''), dict(date='nope')):
            with self.subTest(bad=bad):
                form = IncomeForm(self.data(**bad))
                self.assertFalse(form.is_valid())
        self.assertEqual(Income.objects.count(), 0)

    def test_delete_removes_income_and_restores_balance(self):
        income = self.make_income()
        response = self.client.post(reverse('income:income_delete', args=[income.pk]))
        self.assertRedirects(response, reverse('income:income_list'), fetch_redirect_response=False)
        self.assertEqual(Income.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(get_balance(self.cash), D('1000'))

    def test_delete_rejects_get(self):
        income = self.make_income()
        self.assertEqual(self.client.get(reverse('income:income_delete', args=[income.pk])).status_code, 405)

    def test_missing_income_is_404(self):
        self.assertEqual(self.client.post(reverse('income:income_delete', args=[999])).status_code, 404)

    # ---- categories --------------------------------------------------------

    def test_category_create_edit_delete(self):
        self.client.post(reverse('income:category_add'), {'name': 'Commission'})
        commission = IncomeCategory.objects.get(name='Commission')
        self.client.post(reverse('income:category_edit', args=[commission.pk]), {'name': 'Sales commission'})
        commission.refresh_from_db()
        self.assertEqual(commission.name, 'Sales commission')
        self.client.post(reverse('income:category_delete', args=[commission.pk]))
        self.assertFalse(IncomeCategory.objects.filter(pk=commission.pk).exists())

    def test_duplicate_category_name_is_rejected_ignoring_case(self):
        self.assertFalse(CategoryForm({'name': 'interest'}).is_valid())
        self.assertFalse(CategoryForm({'name': ' RENT '}).is_valid())
        self.assertTrue(CategoryForm({'name': 'Interest'}, instance=self.interest).is_valid())  # itself is fine

    def test_category_with_incomes_cannot_be_deleted(self):
        self.make_income()
        self.client.post(reverse('income:category_delete', args=[self.interest.pk]))
        self.assertTrue(IncomeCategory.objects.filter(pk=self.interest.pk).exists())

    # ---- pages render ------------------------------------------------------

    def test_pages_render(self):
        income = self.make_income()
        for name, args in (
            ('income:income_list', []), ('income:income_add', []), ('income:income_edit', [income.pk]),
            ('income:category_list', []), ('income:category_add', []),
            ('income:category_edit', [self.interest.pk]),
        ):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_invalid_post_shows_the_form_with_errors(self):
        response = self.client.post(reverse('income:income_add'), self.data(amount='0'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Income.objects.count(), 0)
        self.assertContains(response, 'text-danger')

    def test_duplicate_category_post_shows_the_error(self):
        response = self.client.post(reverse('income:category_add'), {'name': 'interest'})
        self.assertContains(response, 'already exists')
        self.assertEqual(IncomeCategory.objects.filter(name__iexact='interest').count(), 1)

    def test_datatable_lists_and_filters_incomes(self):
        self.make_income()
        self.make_income(title='Shop rent', category=self.rent, account=self.bank, date=date(2026, 10, 1))
        url = reverse('income:income_datatable')
        self.assertEqual(self.client.get(url, {'draw': 1}).json()['recordsTotal'], 2)
        for params, expected in (
            ({'category': self.rent.pk}, ['Shop rent']),
            ({'account': self.cash.pk}, ['Savings interest']),
            ({'date_from': '2026-11-01'}, ['Savings interest']),
            ({'date_to': '2026-10-31'}, ['Shop rent']),
        ):
            with self.subTest(params=params):
                rows = self.client.get(url, {'draw': 1, **params}).json()['data']
                self.assertEqual([r['title'] for r in rows], expected)
        row = self.client.get(url, {'draw': 1, 'category': self.rent.pk}).json()['data'][0]
        self.assertEqual((row['amount'], row['date'], row['account']), ('250.00 BDT', '2026-10-01', 'Bank'))

    def test_category_datatable_lists_categories(self):
        data = self.client.get(reverse('income:category_datatable'), {'draw': 1}).json()
        self.assertEqual([r['name'] for r in data['data']], ['Interest', 'Rent'])
