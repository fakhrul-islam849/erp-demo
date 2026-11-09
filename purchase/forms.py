import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django import forms
from django.core.validators import FileExtensionValidator

from payment_account.models import Account
from product.models import Product
from supplier.models import Supplier
from warehouse.models import Warehouse

from .models import INVOICE_EXTENSIONS, Purchase, PurchaseAdjustmentType


class AdjustmentTypeForm(forms.Form):
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    type = forms.ChoiceField(
        choices=PurchaseAdjustmentType.Type.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, adjustment_type=None, **kwargs):
        self.adjustment_type = adjustment_type
        super().__init__(*args, **kwargs)
        if adjustment_type:
            self.fields['name'].initial = adjustment_type.name
            self.fields['type'].initial = adjustment_type.type

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = PurchaseAdjustmentType.objects.filter(name__iexact=name)
        if self.adjustment_type:
            duplicates = duplicates.exclude(pk=self.adjustment_type.pk)
        if duplicates.exists():
            raise forms.ValidationError('An adjustment type with this name already exists.')
        return name

    def save(self):
        data = self.cleaned_data

        adjustment_type = self.adjustment_type or PurchaseAdjustmentType()
        adjustment_type.name = data['name']
        adjustment_type.type = data['type']
        adjustment_type.save()
        return adjustment_type


class PurchaseHeaderForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    account = forms.ModelChoiceField(
        queryset=Account.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    status = forms.ChoiceField(
        choices=[(v, l) for v, l in Purchase.Status.choices if v != Purchase.Status.CANCELLED],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    invoice = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=INVOICE_EXTENSIONS)],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        help_text='PDF, JPG or PNG.',
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def __init__(self, *args, purchase=None, **kwargs):
        self.purchase = purchase
        super().__init__(*args, **kwargs)
        if purchase:
            for name in ('warehouse', 'supplier', 'account', 'date', 'status', 'note'):
                self.fields[name].initial = getattr(purchase, name)
        else:
            self.fields['date'].initial = date.today()

    def header(self):
        """The cleaned values in the shape save_purchase() expects."""
        data = self.cleaned_data
        header = {name: data[name] for name in ('warehouse', 'supplier', 'account', 'date', 'status', 'note')}
        if data.get('invoice'):
            header['invoice'] = data['invoice']
        return header


def parse_decimal(value, label, errors, allow_zero):
    try:
        number = Decimal(str(value).strip()).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        errors.append(f'{label}: enter a valid number.')
        return None
    if number < 0 or (number == 0 and not allow_zero) or number >= Decimal('1e12'):
        errors.append(f'{label}: enter a valid amount.')
        return None
    return number


def parse_adjustments(rows, types, label, errors):
    parsed = []
    for number, row in enumerate(rows or [], start=1):
        row_label = f'{label} adjustment {number}'
        adjustment_type = types.get(parse_int(row.get('type')))
        if adjustment_type is None:
            errors.append(f'{row_label}: choose a type.')
        amount = parse_decimal(row.get('amount', ''), row_label, errors, allow_zero=False)
        if adjustment_type is not None and amount is not None:
            parsed.append((adjustment_type, amount))
    return parsed


def parse_int(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def parse_payload(raw):
    """Turn the JSON built by the purchase form into save_purchase() arguments.

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

    product_ids = [i for i in (parse_int(l.get('product')) for l in raw_lines) if i is not None]
    products = Product.objects.in_bulk(product_ids)
    types = PurchaseAdjustmentType.objects.in_bulk()

    lines = []
    for number, row in enumerate(raw_lines, start=1):
        label = f'Line {number}'
        product = products.get(parse_int(row.get('product')))
        if product is None:
            errors.append(f'{label}: choose a product.')
        quantity = parse_int(row.get('quantity'))
        if quantity is None or quantity <= 0:
            errors.append(f'{label}: quantity must be a whole number above zero.')
        purchase_price = parse_decimal(row.get('purchase_price', ''), f'{label} purchase price', errors, allow_zero=True)
        sale_price = parse_decimal(row.get('sale_price', ''), f'{label} sale price', errors, allow_zero=True)
        line_adjustments = parse_adjustments(row.get('adjustments'), types, label, errors)
        if product and quantity and quantity > 0 and purchase_price is not None and sale_price is not None:
            lines.append({
                'product': product,
                'quantity': quantity,
                'purchase_price': purchase_price,
                'sale_price': sale_price,
                'adjustments': line_adjustments,
            })

    adjustments = parse_adjustments(raw_adjustments, types, 'Purchase', errors)
    if not raw_lines:
        errors.append('Add at least one product.')
    return lines, adjustments, errors


def purchase_to_payload(purchase):
    """The form's JSON state for an existing purchase."""
    lines = []
    for lot in purchase.lots.order_by('id'):
        lines.append({
            'product': lot.product_id,
            'quantity': lot.quantity,
            'purchase_price': str(lot.purchase_price.quantize(Decimal('0.01'))),
            'sale_price': str(lot.sale_price),
            'adjustments': [
                {'type': a.adjustment_type_id, 'amount': str(a.amount)}
                for a in lot.adjustments.order_by('id')
            ],
        })
    adjustments = [
        {'type': a.adjustment_type_id, 'amount': str(a.amount)}
        for a in purchase.adjustments.filter(lot__isnull=True).order_by('id')
    ]
    return {'lines': lines, 'adjustments': adjustments}
