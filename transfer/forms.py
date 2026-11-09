import json
from datetime import date

from django import forms

from payment_account.models import Account
from purchase.forms import parse_adjustments, parse_decimal, parse_int
from purchase.models import PurchaseAdjustmentType, StockLot
from warehouse.models import Warehouse


class TransferHeaderForm(forms.Form):
    from_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    to_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    account = forms.ModelChoiceField(
        queryset=Account.objects.order_by('name'),
        required=False,
        empty_label='No account (no cost)',
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='Needed only when the transfer has a net cost; it is paid from this account on confirm.',
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, transfer=None, **kwargs):
        super().__init__(*args, **kwargs)
        if transfer:
            for name in self.fields:
                self.fields[name].initial = getattr(transfer, name)
        else:
            self.fields['date'].initial = date.today()

    def clean(self):
        cleaned = super().clean()
        source, target = cleaned.get('from_warehouse'), cleaned.get('to_warehouse')
        if source and target and source == target:
            self.add_error('to_warehouse', 'Choose a different warehouse than the one stock is taken from.')
        return cleaned

    def header(self):
        """The cleaned values in the shape save_transfer() expects."""
        return {name: self.cleaned_data[name] for name in self.fields}


def parse_transfer_payload(raw):
    """Turn the JSON built by the transfer form into save_transfer() arguments.

    Returns (lines, adjustments, errors); errors is a list of messages.
    """
    errors = []
    try:
        data = json.loads(raw or '{}')
        raw_lines = data.get('lines') or []
        raw_adjustments = data.get('adjustments') or []
        rows = raw_lines + raw_adjustments + [a for l in raw_lines for a in l.get('adjustments') or []]
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        return [], [], ['The product list could not be read. Please try again.']

    lot_ids = [i for i in (parse_int(l.get('source_lot')) for l in raw_lines) if i is not None]
    lots = StockLot.objects.select_related('product').in_bulk(lot_ids)
    types = PurchaseAdjustmentType.objects.in_bulk()

    lines = []
    for number, row in enumerate(raw_lines, start=1):
        label = f'Line {number}'
        lot = lots.get(parse_int(row.get('source_lot')))
        if lot is None:
            errors.append(f'{label}: choose a product.')
        quantity = parse_int(row.get('quantity'))
        if quantity is None or quantity <= 0:
            errors.append(f'{label}: quantity must be a whole number above zero.')
        sale_price = parse_decimal(row.get('sale_price', ''), f'{label} sale price', errors, allow_zero=True)
        line_adjustments = parse_adjustments(row.get('adjustments'), types, label, errors)
        if lot and quantity and quantity > 0 and sale_price is not None:
            lines.append({
                'source_lot': lot,
                'quantity': quantity,
                'sale_price': sale_price,
                'adjustments': line_adjustments,
            })

    adjustments = parse_adjustments(raw_adjustments, types, 'Transfer', errors)
    if not raw_lines:
        errors.append('Add at least one product.')
    return lines, adjustments, errors


def transfer_to_payload(transfer):
    """The form's JSON state for an existing transfer."""
    lines = []
    for lot in transfer.lots.order_by('id'):
        lines.append({
            'source_lot': lot.source_lot_id,
            'quantity': lot.quantity,
            'sale_price': str(lot.sale_price),
            'adjustments': [
                {'type': a.adjustment_type_id, 'amount': str(a.amount)}
                for a in lot.adjustments.order_by('id')
            ],
        })
    adjustments = [
        {'type': a.adjustment_type_id, 'amount': str(a.amount)}
        for a in transfer.adjustments.filter(lot__isnull=True).order_by('id')
    ]
    return {'lines': lines, 'adjustments': adjustments}
