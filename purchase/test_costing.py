from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .costing import apply_costs

D = Decimal


def lot(pk, quantity, price):
    return SimpleNamespace(pk=pk, quantity=quantity, purchase_price=D(price))


def adjustment(kind, amount, lot_pk=None):
    return SimpleNamespace(
        lot_id=lot_pk, amount=D(amount), adjustment_type=SimpleNamespace(type=kind),
    )


class ApplyCostsTests(SimpleTestCase):
    def test_no_adjustments(self):
        lots = [lot(1, 10, '5')]
        totals = apply_costs(lots, [])
        self.assertEqual(lots[0].landed_cost, D('5.0000'))
        self.assertEqual((totals.subtotal, totals.total_cost, totals.total_discount), (D('50'), D('0'), D('0')))

    def test_header_net_split_by_value(self):
        lots = [lot(1, 10, '5'), lot(2, 5, '20')]
        totals = apply_costs(lots, [adjustment('add', '30')])
        self.assertEqual([l.landed_cost for l in lots], [D('6.0000'), D('24.0000')])
        self.assertEqual((totals.subtotal, totals.total_cost), (D('150'), D('30')))

    def test_line_adjustments_land_on_their_own_lot(self):
        lots = [lot(1, 10, '5'), lot(2, 5, '20')]
        totals = apply_costs(lots, [adjustment('deduct', '5', lot_pk=1), adjustment('add', '30')])
        self.assertEqual((lots[0].cost, lots[0].discount), (D('0'), D('5')))
        self.assertEqual([l.landed_cost for l in lots], [D('5.4310'), D('24.1380')])
        self.assertEqual((totals.total_cost, totals.total_discount), (D('30'), D('5')))

    def test_remainder_goes_to_last_lot_and_lots_sum_exactly(self):
        lots = [lot(i, 1, '10') for i in (1, 2, 3)]
        totals = apply_costs(lots, [adjustment('add', '100')])
        self.assertEqual([l.landed_cost for l in lots], [D('43.3300'), D('43.3300'), D('43.3400')])
        self.assertEqual(
            sum(l.landed_cost * l.quantity for l in lots),
            totals.subtotal + totals.total_cost - totals.total_discount,
        )

    def test_split_by_quantity_when_every_lot_is_free(self):
        lots = [lot(1, 1, '0'), lot(2, 3, '0')]
        apply_costs(lots, [adjustment('add', '40')])
        self.assertEqual([l.landed_cost for l in lots], [D('10.0000'), D('10.0000')])

    def test_four_decimal_price_like_a_transfer_lot(self):
        lots = [lot(1, 3, '6.1234')]
        apply_costs(lots, [adjustment('add', '10')])
        self.assertEqual(lots[0].landed_cost, D('9.4567'))  # (3 x 6.1234 + 10) / 3

    def test_discount_larger_than_value_is_rejected(self):
        with self.assertRaisesMessage(ValidationError, 'transfer line'):
            apply_costs([lot(1, 1, '10')], [adjustment('deduct', '50')], noun='transfer')

    def test_no_lots(self):
        totals = apply_costs([], [])
        self.assertEqual(tuple(totals), (D('0'), D('0'), D('0')))
