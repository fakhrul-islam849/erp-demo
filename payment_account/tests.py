from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Account, Transaction
from .services import get_balance


class GetBalanceTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            name='Test cash', opening_balance=Decimal('1000'), currency='BDT',
        )

    def add(self, type, status, amount):
        return Transaction.objects.create(
            account=self.account, type=type, status=status,
            amount=Decimal(amount), date=date.today(),
        )

    def test_no_transactions_returns_opening_balance(self):
        self.assertEqual(get_balance(self.account), Decimal('1000'))

    def test_settled_rows_counted_pending_ignored(self):
        self.add('purchase', 'paid', '300')
        self.add('sale', 'received', '500')
        self.add('expense', 'pending', '999')
        self.assertEqual(get_balance(self.account), Decimal('1200'))

    def test_cancelled_ignored(self):
        self.add('purchase', 'cancelled', '300')
        self.assertEqual(get_balance(self.account), Decimal('1000'))

    def test_invalid_type_status_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.add('purchase', 'received', '10')
