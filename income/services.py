from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from payment_account.models import Transaction

from .models import Income

FIELDS = ('title', 'account', 'category', 'amount', 'date')


def _validate(values):
    if not str(values.get('title') or '').strip():
        raise ValidationError('Enter a title.')
    if values.get('account') is None:
        raise ValidationError('Choose the account that receives the money.')
    if values.get('category') is None:
        raise ValidationError('Choose a category.')
    amount = values.get('amount')
    if not isinstance(amount, Decimal) or amount <= 0:
        raise ValidationError('Amount must be greater than zero.')


def _sync_transaction(income):
    """Keep the received income transaction identical to the income."""
    values = {
        'account': income.account,
        'type': Transaction.Type.INCOME,
        'status': Transaction.Status.RECEIVED,
        'amount': income.amount,
        'date': income.date,
        'reference': f'Income #{income.pk}: {income.title}',
    }
    if income.transaction_id:
        for field, value in values.items():
            setattr(income.transaction, field, value)
        income.transaction.save()
    else:
        income.transaction = Transaction.objects.create(**values)
        income.save(update_fields=['transaction', 'updated_at'])


@transaction.atomic
def save_income(*, values, income=None):
    """Create an income, or change an existing one; the account balance follows.

    values  dict with title, account, category, amount (Decimal) and date
    """
    _validate(values)
    if income is None:
        income = Income()
    else:
        income = Income.objects.select_for_update().get(pk=income.pk)
    for field in FIELDS:
        setattr(income, field, values[field])
    income.title = income.title.strip()
    income.save()
    _sync_transaction(income)
    return income


@transaction.atomic
def delete_income(income):
    """Remove the income and its transaction, so the balance goes back."""
    income = Income.objects.select_for_update().get(pk=income.pk)
    linked = income.transaction
    income.delete()
    if linked is not None:
        linked.delete()
