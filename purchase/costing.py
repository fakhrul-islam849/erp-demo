"""Cost calculation shared by purchases and transfers.

Works on any list of stock lots plus the adjustments that belong to them, and
does not touch the database; callers save the results.
"""
from collections import namedtuple
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

from .models import PurchaseAdjustmentType

MONEY = Decimal('0.01')
COST = Decimal('0.0001')
ZERO = Decimal('0')

CostTotals = namedtuple('CostTotals', 'subtotal total_cost total_discount')


def _signed(adjustment):
    """Positive for an 'add' adjustment, negative for a 'deduct' one."""
    if adjustment.adjustment_type.type == PurchaseAdjustmentType.Type.ADD:
        return adjustment.amount
    return -adjustment.amount


def _sum(adjustments, sign):
    return sum((a.amount for a in adjustments if _signed(a) * sign > 0), ZERO)


def apply_costs(lots, adjustments, noun='purchase'):
    """Fill cost, discount and landed_cost on every lot, and return the totals.

    Each lot's cost/discount come from the adjustments attached to that lot.
    The net of the adjustments that cover the whole purchase/transfer (no lot)
    is split across the lots by value, with the rounding remainder on the last
    lot, so the lots always add up exactly. If every lot is worth zero, the
    split is by quantity instead.

    The lots are changed in place but not saved. Raises ValidationError when a
    discount makes a lot worth less than nothing.
    """
    lot_adjustments = {lot.pk: [] for lot in lots}
    header_adjustments = []
    for adjustment in adjustments:
        if adjustment.lot_id:
            lot_adjustments[adjustment.lot_id].append(adjustment)
        else:
            header_adjustments.append(adjustment)

    line_nets = []
    for lot in lots:
        lot.cost = _sum(lot_adjustments[lot.pk], 1)
        lot.discount = _sum(lot_adjustments[lot.pk], -1)
        line_nets.append(lot.quantity * lot.purchase_price + lot.cost - lot.discount)

    header_cost = _sum(header_adjustments, 1)
    header_discount = _sum(header_adjustments, -1)
    header_net = header_cost - header_discount

    if sum(line_nets, ZERO) > 0:
        weights = line_nets
    else:
        weights = [Decimal(lot.quantity) for lot in lots]
    total_weight = sum(weights, ZERO)

    allocated_so_far = ZERO
    for index, lot in enumerate(lots):
        if index == len(lots) - 1:
            allocated = header_net - allocated_so_far
        else:
            allocated = (header_net * weights[index] / total_weight).quantize(MONEY, rounding=ROUND_HALF_UP)
            allocated_so_far += allocated

        line_total = line_nets[index] + allocated
        if line_total < 0:
            raise ValidationError(f'Discounts are larger than the value of a {noun} line.')
        lot.landed_cost = (line_total / lot.quantity).quantize(COST, rounding=ROUND_HALF_UP)

    return CostTotals(
        subtotal=sum((lot.quantity * lot.purchase_price for lot in lots), ZERO),
        total_cost=sum((lot.cost for lot in lots), ZERO) + header_cost,
        total_discount=sum((lot.discount for lot in lots), ZERO) + header_discount,
    )
