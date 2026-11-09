import json
from datetime import date

from django import forms

from payment_account.models import Account
from purchase.forms import parse_adjustments, parse_int
from purchase.models import StockLot

from .models import Sale, SaleAdjustmentType


class AdjustmentTypeForm(forms.ModelForm):
    class Meta:
        model = SaleAdjustmentType
        fields = ['name', 'type']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = SaleAdjustmentType.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('An adjustment type with this name already exists.')
        return name


class SaleHeaderForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='The account that receives the money once the sale is received.',
    )
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    payment_status = forms.ChoiceField(
        choices=[
            (Sale.PaymentStatus.PENDING, 'Pending'),
            (Sale.PaymentStatus.RECEIVED, 'Received'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    details = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, sale=None, **kwargs):
        super().__init__(*args, **kwargs)
        if sale:
            for name in self.fields:
                self.fields[name].initial = getattr(sale, name)
            if sale.payment_status == Sale.PaymentStatus.RECEIVED:  # cannot go back to pending
                self.fields['payment_status'].choices = [(Sale.PaymentStatus.RECEIVED, 'Received')]
        else:
            self.fields['date'].initial = date.today()

    def header(self):
        """The cleaned values in the shape save_sale() expects."""
        return {name: self.cleaned_data[name] for name in self.fields}


def parse_sale_payload(raw):
    """Turn the JSON built by the sale form into save_sale() arguments.

    Returns (lines, adjustments, errors); errors is a list of messages.
    The price of a line is not read: it always comes from the stock lot.
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

    lot_ids = [i for i in (parse_int(l.get('lot')) for l in raw_lines) if i is not None]
    lots = StockLot.objects.select_related('product').in_bulk(lot_ids)
    types = SaleAdjustmentType.objects.in_bulk()

    lines = []
    for number, row in enumerate(raw_lines, start=1):
        label = f'Line {number}'
        lot = lots.get(parse_int(row.get('lot')))
        if lot is None:
            errors.append(f'{label}: choose a product.')
        quantity = parse_int(row.get('quantity'))
        if quantity is None or quantity <= 0:
            errors.append(f'{label}: quantity must be a whole number above zero.')
        line_adjustments = parse_adjustments(row.get('adjustments'), types, label, errors)
        if lot and quantity and quantity > 0:
            lines.append({'lot': lot, 'quantity': quantity, 'adjustments': line_adjustments})

    adjustments = parse_adjustments(raw_adjustments, types, 'Sale', errors)
    if not raw_lines:
        errors.append('Add at least one product.')
    return lines, adjustments, errors


def sale_to_payload(sale):
    """The form's JSON state for an existing sale."""
    lines = []
    for line in sale.lines.order_by('id'):
        lines.append({
            'lot': line.lot_id,
            'quantity': line.quantity,
            'adjustments': [
                {'type': a.adjustment_type_id, 'amount': str(a.amount)}
                for a in line.adjustments.order_by('id')
            ],
        })
    adjustments = [
        {'type': a.adjustment_type_id, 'amount': str(a.amount)}
        for a in sale.adjustments.filter(line__isnull=True).order_by('id')
    ]
    return {'lines': lines, 'adjustments': adjustments}
