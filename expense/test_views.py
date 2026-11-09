import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from payment_account.models import Account, Transaction
from payment_account.services import get_balance

from .forms import CategoryForm, ExpenseForm
from .models import Expense, ExpenseCategory
from .services import save_expense

D = Decimal
MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class ExpenseViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user('admin1', password='pw', user_type='admin')
        cls.employee = User.objects.create_user('emp1', password='pw', user_type='employee')
        cls.cash = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        cls.bank = Account.objects.create(name='Bank', opening_balance=D('500'), currency='BDT')
        cls.rent = ExpenseCategory.objects.create(name='Rent')
        cls.repair = ExpenseCategory.objects.create(name='Repair')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.admin)

    def make_expense(self, **kw):
        values = dict(title='Shop rent', account=self.cash, category=self.rent,
                      amount=D('250'), date=date(2026, 11, 5))
        values.update(kw)
        return save_expense(values=values)

    def pdf(self, name='bill.pdf', size=10):
        return SimpleUploadedFile(name, b'x' * size, content_type='application/pdf')

    def data(self, **kw):
        data = dict(title='Fan repair', account=self.cash.pk, category=self.repair.pk,
                    amount='300.00', date='2026-11-05')
        data.update(kw)
        return data

    # ---- access ------------------------------------------------------------

    def test_employee_and_anonymous_are_kept_out(self):
        expense = self.make_expense()
        urls = [reverse('expense:expense_datatable'), reverse('expense:expense_add'),
                reverse('expense:category_datatable'), reverse('expense:category_add'),
                reverse('expense:expense_delete', args=[expense.pk])]
        self.client.force_login(self.employee)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)

    # ---- expense -----------------------------------------------------------

    def test_post_creates_an_expense_with_an_attachment(self):
        response = self.client.post(reverse('expense:expense_add'), self.data(attachment=self.pdf()))
        self.assertRedirects(response, reverse('expense:expense_list'), fetch_redirect_response=False)
        expense = Expense.objects.get()
        self.assertEqual((expense.title, expense.amount, expense.category), ('Fan repair', D('300.00'), self.repair))
        self.assertTrue(expense.attachment.name.endswith('.pdf'))
        self.assertEqual(get_balance(self.cash), D('700'))

    def test_post_without_an_attachment_is_fine(self):
        self.client.post(reverse('expense:expense_add'), self.data())
        self.assertFalse(Expense.objects.get().attachment)

    def test_post_edits_an_expense_and_keeps_its_attachment(self):
        expense = self.make_expense(attachment=self.pdf())
        name = expense.attachment.name
        self.client.post(reverse('expense:expense_edit', args=[expense.pk]),
                         self.data(account=self.bank.pk, amount='100'))
        expense.refresh_from_db()
        self.assertEqual(expense.attachment.name, name)
        self.assertEqual(get_balance(self.cash), D('1000'))
        self.assertEqual(get_balance(self.bank), D('400'))

    def test_edit_can_remove_the_attachment(self):
        expense = self.make_expense(attachment=self.pdf())
        self.client.post(reverse('expense:expense_edit', args=[expense.pk]),
                         self.data(clear_attachment='on'))
        expense.refresh_from_db()
        self.assertFalse(expense.attachment)

    def test_delete_removes_expense_and_restores_balance(self):
        expense = self.make_expense()
        response = self.client.post(reverse('expense:expense_delete', args=[expense.pk]))
        self.assertRedirects(response, reverse('expense:expense_list'), fetch_redirect_response=False)
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(get_balance(self.cash), D('1000'))

    def test_delete_rejects_get_and_missing_expense_is_404(self):
        expense = self.make_expense()
        self.assertEqual(self.client.get(reverse('expense:expense_delete', args=[expense.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse('expense:expense_delete', args=[999])).status_code, 404)

    # ---- form validation ---------------------------------------------------

    def test_form_rejects_bad_input(self):
        for bad in (dict(amount='0'), dict(amount='-1'), dict(amount='abc'), dict(title='  '),
                    dict(category=''), dict(account=''), dict(date='nope')):
            with self.subTest(bad=bad):
                self.assertFalse(ExpenseForm(self.data(**bad)).is_valid())

    def test_form_attachment_rules(self):
        limit = 5 * 1024 * 1024
        cases = (
            (SimpleUploadedFile('a.pdf', b'x'), True),
            (SimpleUploadedFile('a.JPG', b'x'), True),
            (SimpleUploadedFile('a.png', b'x'), True),
            (SimpleUploadedFile('a.exe', b'x'), False),
            (SimpleUploadedFile('a.txt', b'x'), False),
            (SimpleUploadedFile('a.pdf', b'x' * limit), True),
            (SimpleUploadedFile('a.pdf', b'x' * (limit + 1)), False),
        )
        for upload, ok in cases:
            with self.subTest(name=upload.name, size=upload.size):
                form = ExpenseForm(self.data(), {'attachment': upload})
                self.assertEqual(form.is_valid(), ok, form.errors)

    def test_form_tells_the_user_the_limits(self):
        help_text = ExpenseForm().fields['attachment'].help_text
        self.assertIn('PDF, JPG or PNG', help_text)
        self.assertIn('5 MB', help_text)

    def test_remove_checkbox_only_when_there_is_an_attachment(self):
        self.assertNotIn('clear_attachment', ExpenseForm().fields)
        self.assertNotIn('clear_attachment', ExpenseForm(expense=self.make_expense()).fields)
        self.assertIn('clear_attachment', ExpenseForm(expense=self.make_expense(attachment=self.pdf())).fields)

    # ---- categories --------------------------------------------------------

    def test_category_create_edit_delete(self):
        self.client.post(reverse('expense:category_add'), {'name': 'Utilities'})
        utilities = ExpenseCategory.objects.get(name='Utilities')
        self.client.post(reverse('expense:category_edit', args=[utilities.pk]), {'name': 'Bills'})
        utilities.refresh_from_db()
        self.assertEqual(utilities.name, 'Bills')
        self.client.post(reverse('expense:category_delete', args=[utilities.pk]))
        self.assertFalse(ExpenseCategory.objects.filter(pk=utilities.pk).exists())

    def test_duplicate_category_name_is_rejected_ignoring_case(self):
        self.assertFalse(CategoryForm({'name': 'rent'}).is_valid())
        self.assertFalse(CategoryForm({'name': ' REPAIR '}).is_valid())
        self.assertTrue(CategoryForm({'name': 'Rent'}, instance=self.rent).is_valid())

    def test_category_with_expenses_cannot_be_deleted(self):
        self.make_expense()
        self.client.post(reverse('expense:category_delete', args=[self.rent.pk]))
        self.assertTrue(ExpenseCategory.objects.filter(pk=self.rent.pk).exists())

    def test_expense_categories_are_separate_from_income_categories(self):
        from income.models import IncomeCategory
        IncomeCategory.objects.create(name='Interest')
        self.assertFalse(ExpenseCategory.objects.filter(name='Interest').exists())

    # ---- pages render ------------------------------------------------------

    def test_pages_render(self):
        expense = self.make_expense(attachment=self.pdf())
        for name, args in (
            ('expense:expense_list', []), ('expense:expense_add', []), ('expense:expense_edit', [expense.pk]),
            ('expense:category_list', []), ('expense:category_add', []),
            ('expense:category_edit', [self.rent.pk]),
        ):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_form_can_upload_files_and_shows_the_limits(self):
        page = self.client.get(reverse('expense:expense_add')).content.decode()
        self.assertIn('multipart/form-data', page)
        self.assertIn('PDF, JPG or PNG, up to 5 MB', page)
        self.assertNotIn('Remove the current attachment', page)

    def test_edit_form_shows_the_current_file_and_remove_option(self):
        expense = self.make_expense(attachment=self.pdf())
        page = self.client.get(reverse('expense:expense_edit', args=[expense.pk])).content.decode()
        self.assertIn(expense.attachment.url, page)
        self.assertIn('Remove the current attachment', page)

    def test_not_enough_money_shows_the_error_on_the_form(self):
        response = self.client.post(reverse('expense:expense_add'), self.data(amount='1000.01'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cash has 1000.00 BDT available')
        self.assertEqual(Expense.objects.count(), 0)

    def test_wrong_file_type_shows_the_error_on_the_form(self):
        response = self.client.post(
            reverse('expense:expense_add'), self.data(attachment=SimpleUploadedFile('a.exe', b'x')),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not allowed')
        self.assertEqual(Expense.objects.count(), 0)

    def test_duplicate_category_post_shows_the_error(self):
        response = self.client.post(reverse('expense:category_add'), {'name': 'rent'})
        self.assertContains(response, 'already exists')
        self.assertEqual(ExpenseCategory.objects.filter(name__iexact='rent').count(), 1)

    def test_datatable_lists_filters_and_links_attachments(self):
        with_file = self.make_expense(attachment=self.pdf())
        self.make_expense(title='Fan repair', category=self.repair, account=self.bank,
                          amount=D('100'), date=date(2026, 10, 1))
        url = reverse('expense:expense_datatable')
        self.assertEqual(self.client.get(url, {'draw': 1}).json()['recordsTotal'], 2)
        for params, expected in (
            ({'category': self.repair.pk}, ['Fan repair']),
            ({'account': self.cash.pk}, ['Shop rent']),
            ({'date_from': '2026-11-01'}, ['Shop rent']),
            ({'date_to': '2026-10-31'}, ['Fan repair']),
        ):
            with self.subTest(params=params):
                rows = self.client.get(url, {'draw': 1, **params}).json()['data']
                self.assertEqual([r['title'] for r in rows], expected)
        rows = {r['title']: r for r in self.client.get(url, {'draw': 1}).json()['data']}
        self.assertIn(with_file.attachment.url, rows['Shop rent']['attachment'])
        self.assertEqual(rows['Fan repair']['attachment'], '—')
        self.assertEqual(rows['Fan repair']['amount'], '100.00 BDT')

    def test_category_datatable_lists_categories(self):
        data = self.client.get(reverse('expense:category_datatable'), {'draw': 1}).json()
        self.assertEqual([r['name'] for r in data['data']], ['Rent', 'Repair'])
