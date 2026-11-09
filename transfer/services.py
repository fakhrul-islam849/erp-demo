from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from payment_account.models import Transaction
from purchase.costing import apply_costs
from purchase.models import PurchaseAdjustment, StockLot

from .models import Transfer

MONEY = Decimal('0.01')

HEADER_FIELDS = ('from_warehouse', 'to_warehouse', 'date', 'note', 'account')

# the cost of a transfer is only paid once the goods have arrived
TRANSACTION_STATUS = {
    Transfer.Status.IN_TRANSIT: Transaction.Status.PENDING,
    Transfer.Status.CONFIRMED: Transaction.Status.PAID,
    Transfer.Status.CANCELLED: Transaction.Status.CANCELLED,
}


def _validate(header, lines, adjustments):
    if header['from_warehouse'] == header['to_warehouse']:
        raise ValidationError('Choose two different warehouses.')
    if not lines:
        raise ValidationError('A transfer needs at least one product line.')
    for line in lines:
        if not isinstance(line['quantity'], int) or line['quantity'] <= 0:
            raise ValidationError('Quantity must be a whole number above zero.')
        if line['sale_price'] < 0:
            raise ValidationError('Prices cannot be negative.')
    source_ids = [line['source_lot'].pk for line in lines]
    if len(set(source_ids)) != len(source_ids):
        raise ValidationError('The same stock lot is used on more than one line.')
    every_adjustment = list(adjustments) + [a for line in lines for a in line.get('adjustments', ())]
    if any(amount <= 0 for _, amount in every_adjustment):
        raise ValidationError('Adjustment amounts must be greater than zero.')


def _lock(transfer):
    return Transfer.objects.select_for_update().get(pk=transfer.pk)


def _release_stock(transfer):
    """Give the reserved quantities back to the lots they were taken from."""
    for lot in transfer.lots.order_by('source_lot_id'):
        StockLot.objects.filter(pk=lot.source_lot_id).update(
            remaining_quantity=F('remaining_quantity') + lot.quantity,
        )


def _reserve_stock(transfer, lines):
    """Take each line's quantity out of its source lot and create the new lot."""
    ids = sorted(line['source_lot'].pk for line in lines)
    locked = {lot.pk: lot for lot in StockLot.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    usable = set(
        StockLot.objects.available(transfer.from_warehouse).filter(pk__in=ids).values_list('pk', flat=True)
    )

    created = []
    for line in lines:
        source = locked.get(line['source_lot'].pk)
        if source is None or source.pk not in usable:
            raise ValidationError(
                f'Lot #{line["source_lot"].pk} is not available in {transfer.from_warehouse}.'
            )
        if source.remaining_quantity < line['quantity']:
            raise ValidationError(
                f'{source.product}: only {source.remaining_quantity} left in lot #{source.pk}, '
                f'cannot transfer {line["quantity"]}.'
            )
        StockLot.objects.filter(pk=source.pk).update(
            remaining_quantity=F('remaining_quantity') - line['quantity'],
        )
        created.append((line, StockLot.objects.create(
            transfer=transfer,
            source_lot=source,
            product=source.product,
            quantity=line['quantity'],
            remaining_quantity=line['quantity'],
            purchase_price=source.landed_cost,
            sale_price=line['sale_price'],
        )))
    return created


def recalculate_transfer(transfer):
    """Recompute every derived number of a transfer from its saved rows."""
    lots = list(transfer.lots.order_by('id'))
    adjustments = list(transfer.adjustments.select_related('adjustment_type'))

    totals = apply_costs(lots, adjustments, noun='transfer')
    StockLot.objects.bulk_update(lots, ['cost', 'discount', 'landed_cost'])

    transfer.subtotal = totals.subtotal.quantize(MONEY, rounding=ROUND_HALF_UP)
    transfer.total_cost = totals.total_cost
    transfer.total_discount = totals.total_discount
    transfer.save(update_fields=['subtotal', 'total_cost', 'total_discount', 'updated_at'])


def sync_transaction(transfer):
    """Mirror the net cost of the transfer in the account, if there is one."""
    net_cost = transfer.net_cost
    if net_cost > 0:
        values = {
            'account': transfer.account,
            'type': Transaction.Type.TRANSFER,
            'status': TRANSACTION_STATUS[transfer.status],
            'amount': net_cost,
            'date': transfer.date,
            'reference': f'Transfer #{transfer.pk}',
        }
        if transfer.transaction_id:
            for field, value in values.items():
                setattr(transfer.transaction, field, value)
            transfer.transaction.save()
        else:
            transfer.transaction = Transaction.objects.create(**values)
            transfer.save(update_fields=['transaction', 'updated_at'])
    elif transfer.transaction_id:  # the cost was edited away
        transfer.transaction.status = Transaction.Status.CANCELLED
        transfer.transaction.amount = 0
        transfer.transaction.save()


@transaction.atomic
def save_transfer(*, header, lines, adjustments=(), transfer=None):
    """Send a transfer, or fully replace the lines of one that is still in transit.

    header      dict with from_warehouse, to_warehouse, date and optionally
                note and account (needed only when the transfer has a net cost)
    lines       list of dicts: source_lot (a StockLot), quantity, sale_price and
                optionally adjustments=[(adjustment_type, amount), ...]
    adjustments whole-transfer adjustments, [(adjustment_type, amount), ...]
    """
    _validate(header, lines, adjustments)

    if transfer is None:
        transfer = Transfer()
    else:
        transfer = _lock(transfer)
        if transfer.status != Transfer.Status.IN_TRANSIT:
            raise ValidationError('Only a transfer that is in transit can be edited.')
        _release_stock(transfer)
        transfer.lots.all().delete()  # also removes their line adjustments
        transfer.adjustments.all().delete()

    for field in HEADER_FIELDS:
        setattr(transfer, field, header.get(field, '' if field == 'note' else None))
    transfer.save()

    for line, lot in _reserve_stock(transfer, lines):
        for adjustment_type, amount in line.get('adjustments', ()):
            PurchaseAdjustment.objects.create(
                transfer=transfer, lot=lot, adjustment_type=adjustment_type, amount=amount,
            )
    for adjustment_type, amount in adjustments:
        PurchaseAdjustment.objects.create(
            transfer=transfer, adjustment_type=adjustment_type, amount=amount,
        )

    recalculate_transfer(transfer)
    if transfer.net_cost < 0:
        raise ValidationError('Discounts cannot be larger than the costs of a transfer.')
    if transfer.net_cost > 0 and transfer.account_id is None:
        raise ValidationError('Choose the account that pays the transfer cost.')
    sync_transaction(transfer)
    return transfer


@transaction.atomic
def confirm_transfer(transfer):
    """The goods arrived: the new lots become available and the cost is paid."""
    transfer = _lock(transfer)
    if transfer.status != Transfer.Status.IN_TRANSIT:
        raise ValidationError('Only a transfer that is in transit can be confirmed.')
    transfer.status = Transfer.Status.CONFIRMED
    transfer.confirmed_at = timezone.now()
    transfer.save(update_fields=['status', 'confirmed_at', 'updated_at'])
    sync_transaction(transfer)
    return transfer


@transaction.atomic
def cancel_transfer(transfer):
    """Stop a transfer in transit: the stock goes back and nothing is paid.

    The new lots are kept for the record; they never become available.
    """
    transfer = _lock(transfer)
    if transfer.status == Transfer.Status.CANCELLED:
        return transfer
    if transfer.status == Transfer.Status.CONFIRMED:
        raise ValidationError('A confirmed transfer cannot be cancelled.')
    _release_stock(transfer)
    transfer.status = Transfer.Status.CANCELLED
    transfer.save(update_fields=['status', 'updated_at'])
    sync_transaction(transfer)
    return transfer
