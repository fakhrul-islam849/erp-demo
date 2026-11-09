from django.db import models

from common.constants import CURRENCY_CHOICES


class Account(models.Model):
    name = models.CharField(max_length=255)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_account'

    def __str__(self):
        return self.name


class Transaction(models.Model):
    class Type(models.TextChoices):
        PURCHASE = 'purchase', 'Purchase'
        SALE = 'sale', 'Sale'
        EXPENSE = 'expense', 'Expense'
        INCOME = 'income', 'Income'
        TRANSFER = 'transfer', 'Transfer'
        REFUND = 'refund', 'Refund'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        RECEIVED = 'received', 'Received'
        CANCELLED = 'cancelled', 'Cancelled'

    # money leaves the account for these types, enters for the rest
    OUTFLOW_TYPES = (Type.PURCHASE, Type.EXPENSE, Type.TRANSFER, Type.REFUND)
    INFLOW_TYPES = (Type.SALE, Type.INCOME)

    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transactions')
    type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_transaction'
        ordering = ['-date', '-id']
        constraints = [
            models.CheckConstraint(
                check=models.Q(amount__gte=0),
                name='transaction_amount_non_negative',
            ),
            models.CheckConstraint(
                check=(
                    models.Q(type__in=['purchase', 'expense', 'transfer', 'refund'], status__in=['pending', 'paid', 'cancelled'])
                    | models.Q(type__in=['sale', 'income'], status__in=['pending', 'received', 'cancelled'])
                ),
                name='transaction_type_status_valid',
            ),
        ]

    def __str__(self):
        return f'{self.type} {self.amount} ({self.status})'
