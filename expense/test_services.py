import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.test import TestCase, override_settings

from payment_account.models import Account, Transaction
from payment_account.services import get_balance

from .models import Expense, ExpenseCategory
from .services import delete_expense, save_expense

D = Decimal
MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class ExpenseServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cash = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        cls.bank = Account.objects.create(name='Bank', opening_balance=D('500'), currency='BDT')
        cls.rent = ExpenseCategory.objects.create(name='Rent')
        cls.repair = ExpenseCategory.objects.create(name='Repair')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def values(self, **kw):
        values = dict(title='Shop rent', account=self.cash, category=self.rent,
                      amount=D('250.00'), date=date(2026, 11, 5))
        values.update(kw)
        return values

    def pdf(self, name='bill.pdf', size=10):
        return SimpleUploadedFile(name, b'x' * size, content_type='application/pdf')

    def save(self, **kw):
        with self.captureOnCommitCallbacks(execute=True):
            return save_expense(**kw)

    def delete(self, expense):
        with self.captureOnCommitCallbacks(execute=True):
            delete_expense(expense)

    # ---- balance -----------------------------------------------------------

    def test_create_takes_the_amount_out_straight_away(self):
        expense = self.save(values=self.values())
        self.assertEqual(get_balance(self.cash), D('750'))
        transaction = expense.transaction
        self.assertEqual((transaction.type, transaction.status), ('expense', 'paid'))
        self.assertEqual((transaction.account, transaction.amount, transaction.date),
                         (self.cash, D('250.00'), date(2026, 11, 5)))

    def test_edit_amount_moves_the_balance(self):
        expense = self.save(values=self.values())
        self.save(values=self.values(amount=D('400')), expense=expense)
        self.assertEqual(get_balance(self.cash), D('600'))
        self.assertEqual(Transaction.objects.filter(type='expense').count(), 1)

    def test_edit_account_moves_the_money_between_accounts(self):
        expense = self.save(values=self.values())
        self.save(values=self.values(account=self.bank, amount=D('100')), expense=expense)
        self.assertEqual(get_balance(self.cash), D('1000'))
        self.assertEqual(get_balance(self.bank), D('400'))

    def test_edit_other_fields(self):
        expense = self.save(values=self.values())
        expense = self.save(
            values=self.values(title='  Fan repair ', category=self.repair, date=date(2026, 10, 1)), expense=expense,
        )
        expense.refresh_from_db()
        self.assertEqual((expense.title, expense.category, expense.date), ('Fan repair', self.repair, date(2026, 10, 1)))
        self.assertEqual(expense.transaction.date, date(2026, 10, 1))

    def test_delete_restores_the_balance_and_removes_the_transaction(self):
        expense = self.save(values=self.values())
        self.delete(expense)
        self.assertEqual(get_balance(self.cash), D('1000'))
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    # ---- overdraft rule ----------------------------------------------------

    def test_expense_larger_than_the_balance_is_blocked(self):
        with self.assertRaises(ValidationError) as caught:
            self.save(values=self.values(amount=D('1000.01')))
        self.assertIn('1000.00 BDT available', caught.exception.messages[0])
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_expense_of_exactly_the_balance_is_allowed(self):
        self.save(values=self.values(amount=D('1000')))
        self.assertEqual(get_balance(self.cash), D('0'))

    def test_pending_and_cancelled_money_is_not_available_or_spent(self):
        Transaction.objects.create(account=self.cash, type='income', status='pending', amount=D('5000'), date=date.today())
        with self.assertRaises(ValidationError):
            self.save(values=self.values(amount=D('1001')))

    def test_edit_gets_its_own_old_amount_back_when_checking(self):
        expense = self.save(values=self.values(amount=D('900')))  # 100 left
        self.save(values=self.values(amount=D('1000')), expense=expense)  # 100 + 900 available
        self.assertEqual(get_balance(self.cash), D('0'))
        with self.assertRaises(ValidationError):
            self.save(values=self.values(amount=D('1000.01')), expense=expense)
        self.assertEqual(get_balance(self.cash), D('0'))

    def test_moving_to_another_account_needs_the_full_amount_there(self):
        expense = self.save(values=self.values(amount=D('600')))
        with self.assertRaises(ValidationError):
            self.save(values=self.values(account=self.bank, amount=D('600')), expense=expense)
        expense.refresh_from_db()
        self.assertEqual(expense.account, self.cash)
        self.assertEqual(get_balance(self.cash), D('400'))

    # ---- validation --------------------------------------------------------

    def test_invalid_values_are_rejected_and_nothing_is_saved(self):
        for bad in (
            dict(amount=D('0')), dict(amount=D('-5')), dict(amount=5), dict(title='   '),
            dict(account=None), dict(category=None),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.save(values=self.values(**bad))
        self.assertEqual(Expense.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_category_with_expenses_cannot_be_deleted(self):
        self.save(values=self.values())
        with self.assertRaises(ProtectedError):
            self.rent.delete()

    # ---- attachment --------------------------------------------------------

    def test_attachment_is_optional(self):
        self.assertFalse(self.save(values=self.values()).attachment)

    def test_attachment_is_stored(self):
        expense = self.save(values=self.values(attachment=self.pdf()))
        self.assertTrue(expense.attachment.name.endswith('.pdf'))
        self.assertTrue(expense.attachment.storage.exists(expense.attachment.name))

    def test_wrong_type_and_oversized_attachments_are_rejected(self):
        for upload in (
            SimpleUploadedFile('run.exe', b'x'), SimpleUploadedFile('notes.txt', b'x'),
            self.pdf(size=5 * 1024 * 1024 + 1),
        ):
            with self.subTest(name=upload.name), self.assertRaises(ValidationError):
                self.save(values=self.values(attachment=upload))
        self.assertEqual(Expense.objects.count(), 0)

    def test_attachment_of_exactly_the_limit_is_accepted(self):
        self.save(values=self.values(attachment=self.pdf(size=5 * 1024 * 1024)))
        self.assertEqual(Expense.objects.count(), 1)

    def test_edit_without_a_file_keeps_the_attachment(self):
        expense = self.save(values=self.values(attachment=self.pdf()))
        name = expense.attachment.name
        expense = self.save(values=self.values(title='New title'), expense=expense)
        self.assertEqual(expense.attachment.name, name)
        self.assertTrue(expense.attachment.storage.exists(name))

    def test_new_file_replaces_and_removes_the_old_one(self):
        expense = self.save(values=self.values(attachment=self.pdf('one.pdf')))
        old = expense.attachment.name
        expense = self.save(values=self.values(attachment=self.pdf('two.pdf')), expense=expense)
        self.assertNotEqual(expense.attachment.name, old)
        self.assertFalse(expense.attachment.storage.exists(old))
        self.assertTrue(expense.attachment.storage.exists(expense.attachment.name))

    def test_clear_attachment_removes_the_file(self):
        expense = self.save(values=self.values(attachment=self.pdf()))
        old = expense.attachment.name
        expense = self.save(values=self.values(clear_attachment=True), expense=expense)
        self.assertFalse(expense.attachment)
        self.assertFalse(expense.attachment.storage.exists(old))

    def test_delete_removes_the_file(self):
        expense = self.save(values=self.values(attachment=self.pdf()))
        name = expense.attachment.name
        storage = expense.attachment.storage
        self.delete(expense)
        self.assertFalse(storage.exists(name))

    def test_failed_edit_keeps_the_old_file(self):
        expense = self.save(values=self.values(attachment=self.pdf('one.pdf')))
        old = expense.attachment.name
        with self.assertRaises(ValidationError):
            self.save(values=self.values(attachment=self.pdf('two.pdf'), amount=D('5000')), expense=expense)
        self.assertTrue(expense.attachment.storage.exists(old))
