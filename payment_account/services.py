from decimal import Decimal

from django.db.models import Sum

from .models import Transaction


def get_balance(account):
    """opening balance + settled inflows - settled outflows."""
    settled = account.transactions.all()

    inflow = settled.filter(
        type__in=Transaction.INFLOW_TYPES,
        status=Transaction.Status.RECEIVED,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    outflow = settled.filter(
        type__in=Transaction.OUTFLOW_TYPES,
        status=Transaction.Status.PAID,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return account.opening_balance + inflow - outflow