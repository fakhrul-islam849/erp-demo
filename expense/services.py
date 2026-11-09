from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import transaction

from payment_account.models import Account, Transaction
from payment_account.services import get_balance

from .models import ATTACHMENT_EXTENSIONS, Expense, validate_attachment_size

FIELDS = ('title', 'account', 'category', 'amount', 'date')


def _validate(values):
    if not str(values.get('title') or '').strip():
        raise ValidationError('Enter a title.')
    if values.get('account') is None:
        raise ValidationError('Choose the account the expense is paid from.')
    if values.get('category') is None:
        raise ValidationError('Choose a category.')
    amount = values.get('amount')
    if not isinstance(amount, Decimal) or amount <= 0:
        raise ValidationError('Amount must be greater than zero.')
    attachment = values.get('attachment')
    if attachment:
        FileExtensionValidator(allowed_extensions=ATTACHMENT_EXTENSIONS)(attachment)
        validate_attachment_size(attachment)


def _check_funds(expense, account, amount):
    """The account, with this expense's old amount given back, must cover the new amount."""
    available = get_balance(account)
    old = expense.transaction if expense.transaction_id else None
    if old is not None and old.account_id == account.pk and old.status == Transaction.Status.PAID:
        available += old.amount
    if amount > available:
        raise ValidationError(
            f'{account.name} has {available} {account.currency} available; this expense is {amount}.'
        )


def _sync_transaction(expense):
    """Keep the paid expense transaction identical to the expense."""
    values = {
        'account': expense.account,
        'type': Transaction.Type.EXPENSE,
        'status': Transaction.Status.PAID,
        'amount': expense.amount,
        'date': expense.date,
        'reference': f'Expense #{expense.pk}: {expense.title}',
    }
    if expense.transaction_id:
        for field, value in values.items():
            setattr(expense.transaction, field, value)
        expense.transaction.save()
    else:
        expense.transaction = Transaction.objects.create(**values)
        expense.save(update_fields=['transaction', 'updated_at'])


def _delete_file_after_commit(field_file):
    """Remove an unused file only once the database change is permanent."""
    if field_file and field_file.name:
        storage, name = field_file.storage, field_file.name
        transaction.on_commit(lambda: storage.delete(name))


@transaction.atomic
def save_expense(*, values, expense=None):
    """Create an expense, or change an existing one; the account balance follows.

    values  dict with title, account, category, amount (Decimal) and date, and
            optionally attachment (an uploaded file that replaces the old one)
            or clear_attachment=True (remove it)
    Raises ValidationError when the account cannot cover the amount.
    """
    _validate(values)

    # lock the account first so two expenses cannot both spend the same money
    account = Account.objects.select_for_update().get(pk=values['account'].pk)
    if expense is None:
        expense = Expense()
    else:
        expense = Expense.objects.select_for_update().get(pk=expense.pk)
    _check_funds(expense, account, values['amount'])

    old_file = expense.attachment
    old_name = old_file.name if old_file else ''
    for field in FIELDS:
        setattr(expense, field, values[field])
    expense.title = expense.title.strip()
    if values.get('attachment'):
        expense.attachment = values['attachment']
    elif values.get('clear_attachment'):
        expense.attachment = ''
    expense.save()
    if old_name and expense.attachment.name != old_name:
        _delete_file_after_commit(old_file)

    _sync_transaction(expense)
    return expense


@transaction.atomic
def delete_expense(expense):
    """Remove the expense, its transaction and its attachment, so the balance goes back."""
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    linked = expense.transaction
    attachment = expense.attachment
    expense.delete()
    if linked is not None:
        linked.delete()
    _delete_file_after_commit(attachment)
