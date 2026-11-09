from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from payment_account.models import Account, Transaction
from payment_account.services import get_balance

from .models import Income, IncomeCategory
from .services import delete_income, save_income

D = Decimal


class IncomeServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cash = Account.objects.create(name='Cash', opening_balance=D('1000'), currency='BDT')
        cls.bank = Account.objects.create(name='Bank', opening_balance=D('500'), currency='BDT')
        cls.interest = IncomeCategory.objects.create(name='Interest')
        cls.rent = IncomeCategory.objects.create(name='Rent')

    def values(self, **kw):
        values = dict(title='Savings interest', account=self.cash, category=self.interest,
                      amount=D('250.00'), date=date(2026, 11, 5))
        values.update(kw)
        return values

    def test_create_adds_to_the_account_straight_away(self):
        income = save_income(values=self.values())
        self.assertEqual(get_balance(self.cash), D('1250'))
        transaction = income.transaction
        self.assertEqual((transaction.type, transaction.status), ('income', 'received'))
        self.assertEqual((transaction.account, transaction.amount, transaction.date),
                         (self.cash, D('250.00'), date(2026, 11, 5)))

    def test_edit_amount_moves_the_balance(self):
        income = save_income(values=self.values())
        save_income(values=self.values(amount=D('400')), income=income)
        self.assertEqual(get_balance(self.cash), D('1400'))
        self.assertEqual(Transaction.objects.filter(type='income').count(), 1)

    def test_edit_account_moves_money_between_accounts(self):
        income = save_income(values=self.values())
        save_income(values=self.values(account=self.bank), income=income)
        self.assertEqual(get_balance(self.cash), D('1000'))
        self.assertEqual(get_balance(self.bank), D('750'))

    def test_edit_other_fields(self):
        income = save_income(values=self.values())
        income = save_income(
            values=self.values(title='  Shop rent ', category=self.rent, date=date(2026, 10, 1)), income=income,
        )
        income.refresh_from_db()
        self.assertEqual((income.title, income.category, income.date), ('Shop rent', self.rent, date(2026, 10, 1)))
        self.assertEqual(income.transaction.date, date(2026, 10, 1))

    def test_delete_restores_the_balance_and_removes_the_transaction(self):
        income = save_income(values=self.values())
        delete_income(income)
        self.assertEqual(get_balance(self.cash), D('1000'))
        self.assertEqual(Income.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_invalid_values_are_rejected_and_nothing_is_saved(self):
        for bad in (
            dict(amount=D('0')), dict(amount=D('-5')), dict(amount=5), dict(title='   '),
            dict(account=None), dict(category=None),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                save_income(values=self.values(**bad))
        self.assertEqual(Income.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_failed_edit_leaves_income_and_balance_unchanged(self):
        income = save_income(values=self.values())
        with self.assertRaises(ValidationError):
            save_income(values=self.values(amount=D('0')), income=income)
        income.refresh_from_db()
        self.assertEqual(income.amount, D('250.00'))
        self.assertEqual(get_balance(self.cash), D('1250'))

    def test_category_with_income_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        save_income(values=self.values())
        with self.assertRaises(ProtectedError):
            self.interest.delete()
