from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from payment_account.models import Transaction
from purchase.models import StockLot

from .models import Sale, SaleAdjustment, SaleAdjustmentType, SaleLine

MONEY = Decimal('0.01')
ZERO = Decimal('0')

HEADER_FIELDS = ('account', 'date', 'details')

# payment status a caller may ask for when saving; a refund has its own action
SAVE_PAYMENT_STATUSES = (Sale.PaymentStatus.PENDING, Sale.PaymentStatus.RECEIVED)


def _money(value):
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _signed(adjustment_type, amount):
    return amount if adjustment_type.type == SaleAdjustmentType.Type.ADD else -amount


def _validate(header, lines, adjustments, sale):
    if not lines:
        raise ValidationError('A sale needs at least one product line.')
    for line in lines:
        if not isinstance(line['quantity'], int) or line['quantity'] <= 0:
            raise ValidationError('Quantity must be a whole number above zero.')
    lot_ids = [line['lot'].pk for line in lines]
    if len(set(lot_ids)) != len(lot_ids):
        raise ValidationError('The same stock lot is used on more than one line.')
    every_adjustment = list(adjustments) + [a for line in lines for a in line.get('adjustments', ())]
    if any(amount <= 0 for _, amount in every_adjustment):
        raise ValidationError('Adjustment amounts must be greater than zero.')

    payment_status = header.get('payment_status', sale.payment_status if sale else Sale.PaymentStatus.PENDING)
    if payment_status not in SAVE_PAYMENT_STATUSES:
        raise ValidationError('A sale is saved as pending or received; use the refund action to refund it.')
    if sale and sale.payment_status == Sale.PaymentStatus.RECEIVED and payment_status != Sale.PaymentStatus.RECEIVED:
        raise ValidationError('A received sale cannot go back to pending.')
    if header.get('account') is None:
        raise ValidationError('Choose the account that receives the money.')


def _lock(sale):
    return Sale.objects.select_for_update().get(pk=sale.pk)


def _release_stock(sale):
    """Put every line's quantity back on the lot it was taken from."""
    for line in sale.lines.order_by('lot_id'):
        StockLot.objects.filter(pk=line.lot_id).update(
            remaining_quantity=F('remaining_quantity') + line.quantity,
        )


def _reserve_stock(sale, lines, kept_prices):
    """Take each line's quantity out of its lot and create the sale lines.

    A lot that was already on the sale keeps its old price; otherwise the
    price is copied from the lot as it is now.
    """
    ids = sorted(line['lot'].pk for line in lines)
    locked = {lot.pk: lot for lot in StockLot.objects.select_for_update().filter(pk__in=ids).order_by('pk')}
    usable = set(StockLot.objects.available().filter(pk__in=ids).values_list('pk', flat=True))

    created = []
    for line in lines:
        lot = locked.get(line['lot'].pk)
        if lot is None or lot.pk not in usable:
            raise ValidationError(f'Lot #{line["lot"].pk} is not available for sale.')
        # on edit the quantity this sale held was just released, so it counts as free again
        if lot.remaining_quantity < line['quantity']:
            raise ValidationError(
                f'{lot.product}: only {lot.remaining_quantity} left in lot #{lot.pk}, '
                f'cannot sell {line["quantity"]}.'
            )
        StockLot.objects.filter(pk=lot.pk).update(
            remaining_quantity=F('remaining_quantity') - line['quantity'],
        )
        created.append((line, SaleLine.objects.create(
            sale=sale,
            lot=lot,
            quantity=line['quantity'],
            sale_price=kept_prices.get(lot.pk, lot.sale_price),
        )))
    return created


def recalculate_sale(sale):
    """Recompute every derived number of a sale from its saved rows."""
    lines = list(sale.lines.all())
    by_line = {line.pk: [] for line in lines}
    sale_add = sale_deduct = ZERO
    for adjustment in sale.adjustments.select_related('adjustment_type'):
        if adjustment.line_id is None:
            if _signed(adjustment.adjustment_type, adjustment.amount) > 0:
                sale_add += adjustment.amount
            else:
                sale_deduct += adjustment.amount
        else:
            by_line[adjustment.line_id].append(adjustment)

    subtotal = lines_add = lines_deduct = ZERO
    for line in lines:
        line.add_total = sum(
            (a.amount for a in by_line[line.pk] if _signed(a.adjustment_type, a.amount) > 0), ZERO,
        )
        line.deduct_total = sum(
            (a.amount for a in by_line[line.pk] if _signed(a.adjustment_type, a.amount) < 0), ZERO,
        )
        line.line_total = _money(line.quantity * line.sale_price + line.add_total - line.deduct_total)
        if line.line_total < 0:
            raise ValidationError(f'{line.lot.product}: the discount is larger than the line total.')
        subtotal += line.line_total
        lines_add += line.add_total
        lines_deduct += line.deduct_total
    SaleLine.objects.bulk_update(lines, ['add_total', 'deduct_total', 'line_total'])

    sale.subtotal = _money(subtotal)
    sale.lines_add = _money(lines_add)
    sale.lines_deduct = _money(lines_deduct)
    sale.sale_add = _money(sale_add)
    sale.sale_deduct = _money(sale_deduct)
    sale.total_amount = _money(subtotal + sale_add - sale_deduct)
    if sale.total_amount < 0:
        raise ValidationError('The discounts are larger than the sale total.')
    sale.save(update_fields=[
        'subtotal', 'lines_add', 'lines_deduct', 'sale_add', 'sale_deduct', 'total_amount', 'updated_at',
    ])


def sync_transaction(sale):
    """A received sale puts its total amount in the account; nothing before that."""
    if sale.payment_status != Sale.PaymentStatus.RECEIVED:
        return
    values = {
        'account': sale.account,
        'type': Transaction.Type.SALE,
        'status': Transaction.Status.RECEIVED,
        'amount': sale.total_amount,
        'date': sale.date,
        'reference': f'Sale #{sale.pk}',
    }
    if sale.transaction_id:
        for field, value in values.items():
            setattr(sale.transaction, field, value)
        sale.transaction.save()
    else:
        sale.transaction = Transaction.objects.create(**values)
        sale.save(update_fields=['transaction', 'updated_at'])


@transaction.atomic
def save_sale(*, header, lines, adjustments=(), sale=None):
    """Create a sale, or fully replace the lines of one that is still sold and not refunded.

    header      dict with account, date and optionally details and
                payment_status ('pending' or 'received')
    lines       list of dicts: lot (a StockLot), quantity and optionally
                adjustments=[(adjustment_type, amount), ...]
    adjustments whole-sale adjustments, [(adjustment_type, amount), ...]
    The price of a line is never given: it is the lot's sale price.
    """
    _validate(header, lines, adjustments, sale)

    kept_prices = {}
    if sale is None:
        sale = Sale()
    else:
        sale = _lock(sale)
        if sale.status != Sale.Status.SOLD or sale.payment_status == Sale.PaymentStatus.REFUND:
            raise ValidationError('Only a sold sale that was not refunded can be edited.')
        kept_prices = {line.lot_id: line.sale_price for line in sale.lines.all()}
        _release_stock(sale)
        sale.lines.all().delete()  # also removes their line adjustments
        sale.adjustments.all().delete()

    for field in HEADER_FIELDS:
        setattr(sale, field, header.get(field, '' if field == 'details' else None))
    sale.payment_status = header.get('payment_status', sale.payment_status or Sale.PaymentStatus.PENDING)
    sale.save()

    for line, sale_line in _reserve_stock(sale, lines, kept_prices):
        for adjustment_type, amount in line.get('adjustments', ()):
            SaleAdjustment.objects.create(
                sale=sale, line=sale_line, adjustment_type=adjustment_type, amount=amount,
            )
    for adjustment_type, amount in adjustments:
        SaleAdjustment.objects.create(sale=sale, adjustment_type=adjustment_type, amount=amount)

    recalculate_sale(sale)
    sync_transaction(sale)
    return sale


@transaction.atomic
def return_sale(sale):
    """The customer sent everything back: each line's quantity returns to its own lot."""
    sale = _lock(sale)
    if sale.status != Sale.Status.SOLD:
        raise ValidationError('Only a sold sale can be returned.')
    _release_stock(sale)
    sale.status = Sale.Status.RETURNED
    sale.save(update_fields=['status', 'updated_at'])
    return sale


@transaction.atomic
def damage_sale(sale):
    """The goods are damaged: the stock stays deducted and the status is final."""
    sale = _lock(sale)
    if sale.status != Sale.Status.SOLD:
        raise ValidationError('Only a sold sale can be marked damaged.')
    sale.status = Sale.Status.DAMAGED
    sale.save(update_fields=['status', 'updated_at'])
    return sale


@transaction.atomic
def refund_sale(sale, date=None):
    """Pay the received money back to the customer, recorded as its own transaction."""
    sale = _lock(sale)
    if sale.payment_status != Sale.PaymentStatus.RECEIVED:
        raise ValidationError('Only a sale whose money was received can be refunded.')
    sale.refund_transaction = Transaction.objects.create(
        account=sale.account,
        type=Transaction.Type.REFUND,
        status=Transaction.Status.PAID,
        amount=sale.total_amount,
        date=date or sale.date,
        reference=f'Refund of Sale #{sale.pk}',
    )
    sale.payment_status = Sale.PaymentStatus.REFUND
    sale.save(update_fields=['refund_transaction', 'payment_status', 'updated_at'])
    return sale
