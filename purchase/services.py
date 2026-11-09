from django.core.exceptions import ValidationError
from django.db import transaction

from payment_account.models import Transaction

from .costing import apply_costs
from .models import Purchase, PurchaseAdjustment, StockLot

HEADER_FIELDS = ('warehouse', 'supplier', 'account', 'date', 'status', 'note')


def is_locked(purchase):
    """True once any stock from this purchase has been sold or transferred."""
    return any(d.remaining_quantity != d.quantity for d in purchase.lots.all())


def recalculate_purchase(purchase):
    """Recompute every derived number of a purchase from its saved rows."""
    lots = list(purchase.lots.order_by('id'))
    adjustments = list(purchase.adjustments.select_related('adjustment_type'))

    totals = apply_costs(lots, adjustments, noun='purchase')
    StockLot.objects.bulk_update(lots, ['cost', 'discount', 'landed_cost'])

    purchase.subtotal = totals.subtotal
    purchase.total_cost = totals.total_cost
    purchase.total_discount = totals.total_discount
    purchase.total_amount = totals.subtotal + totals.total_cost - totals.total_discount
    purchase.save(update_fields=[
        'subtotal', 'total_cost', 'total_discount', 'total_amount', 'updated_at',
    ])


def sync_transaction(purchase):
    """Create or update the account transaction that mirrors this purchase."""
    values = {
        'account': purchase.account,
        'type': Transaction.Type.PURCHASE,
        'status': purchase.status,
        'amount': purchase.total_amount,
        'date': purchase.date,
        'reference': f'Purchase #{purchase.pk}',
    }
    if purchase.transaction_id:
        for field, value in values.items():
            setattr(purchase.transaction, field, value)
        purchase.transaction.save()
    else:
        purchase.transaction = Transaction.objects.create(**values)
        purchase.save(update_fields=['transaction', 'updated_at'])


def _validate(header, lines, adjustments):
    if not lines:
        raise ValidationError('A purchase needs at least one product line.')
    for line in lines:
        if line['quantity'] <= 0:
            raise ValidationError('Quantity must be greater than zero.')
        if line['purchase_price'] < 0 or line['sale_price'] < 0:
            raise ValidationError('Prices cannot be negative.')
    every_adjustment = list(adjustments) + [a for line in lines for a in line.get('adjustments', ())]
    if any(amount <= 0 for _, amount in every_adjustment):
        raise ValidationError('Adjustment amounts must be greater than zero.')
    if header.get('status') not in Purchase.Status.values:
        raise ValidationError('Invalid purchase status.')


@transaction.atomic
def save_purchase(*, header, lines, adjustments=(), purchase=None):
    """Create a purchase, or fully replace the lines of an existing one.

    header      dict with warehouse, supplier, account, date, status, note and
                optionally invoice (leave it out to keep the current file)
    lines       list of dicts: product, quantity, purchase_price, sale_price and
                optionally adjustments=[(adjustment_type, amount), ...]
    adjustments whole-purchase adjustments, [(adjustment_type, amount), ...]
    """
    _validate(header, lines, adjustments)

    if purchase is None:
        purchase = Purchase()
    else:
        purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
        if purchase.status == Purchase.Status.CANCELLED:
            raise ValidationError('A cancelled purchase cannot be edited.')
        if is_locked(purchase):
            raise ValidationError('Stock from this purchase has already been used, so it cannot be edited.')

    for field in HEADER_FIELDS:
        setattr(purchase, field, header[field])
    if 'invoice' in header:
        purchase.invoice = header['invoice']
    purchase.save()

    purchase.lots.all().delete()  # also removes their line adjustments
    purchase.adjustments.all().delete()

    for line in lines:
        lot = StockLot.objects.create(
            purchase=purchase,
            product=line['product'],
            quantity=line['quantity'],
            remaining_quantity=line['quantity'],
            purchase_price=line['purchase_price'],
            sale_price=line['sale_price'],
        )
        for adjustment_type, amount in line.get('adjustments', ()):
            PurchaseAdjustment.objects.create(
                purchase=purchase, lot=lot, adjustment_type=adjustment_type, amount=amount,
            )
    for adjustment_type, amount in adjustments:
        PurchaseAdjustment.objects.create(
            purchase=purchase, adjustment_type=adjustment_type, amount=amount,
        )

    recalculate_purchase(purchase)
    sync_transaction(purchase)
    return purchase


@transaction.atomic
def cancel_purchase(purchase):
    purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status == Purchase.Status.CANCELLED:
        return purchase
    if is_locked(purchase):
        raise ValidationError('Stock from this purchase has already been used, so it cannot be cancelled.')

    purchase.status = Purchase.Status.CANCELLED
    purchase.save(update_fields=['status', 'updated_at'])
    sync_transaction(purchase)
    return purchase
