import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.mixins import AdminRequiredMixin
from common.search import search_page
from purchase.forms import parse_int
from purchase.models import StockLot

from .forms import AdjustmentTypeForm, SaleHeaderForm, parse_sale_payload, sale_to_payload
from .models import Sale, SaleAdjustmentType
from .services import damage_sale, refund_sale, return_sale, save_sale

STATUS_BADGES = {
    Sale.Status.SOLD: 'success',
    Sale.Status.RETURNED: 'warning',
    Sale.Status.DAMAGED: 'danger',
}
PAYMENT_BADGES = {
    Sale.PaymentStatus.PENDING: 'warning',
    Sale.PaymentStatus.RECEIVED: 'success',
    Sale.PaymentStatus.REFUND: 'secondary',
}


def is_editable(sale):
    return sale.status == Sale.Status.SOLD and sale.payment_status != Sale.PaymentStatus.REFUND


# ---- adjustment types ------------------------------------------------------

class AdjustmentTypeListView(AdminRequiredMixin, TemplateView):
    template_name = 'sale/adjustment_type/list.html'


class AdjustmentTypeDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'search_fields': ['type'], 'order_field': 'type'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return SaleAdjustmentType.objects.all()

    def render_row(self, obj):
        return {
            'name': obj.name,
            'type': obj.get_type_display(),
            'actions': render_to_string('sale/adjustment_type/row_actions.html', {'adjustment_type': obj}),
        }


class AdjustmentTypeFormView(AdminRequiredMixin, View):
    template_name = 'sale/adjustment_type/form.html'

    def get_object(self, pk):
        return get_object_or_404(SaleAdjustmentType, pk=pk) if pk else None

    def get(self, request, pk=None):
        adjustment_type = self.get_object(pk)
        form = AdjustmentTypeForm(instance=adjustment_type)
        return render(request, self.template_name, {'form': form, 'adjustment_type': adjustment_type})

    def post(self, request, pk=None):
        adjustment_type = self.get_object(pk)
        form = AdjustmentTypeForm(request.POST, instance=adjustment_type)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                'Adjustment type updated successfully.' if adjustment_type else 'Adjustment type added successfully.',
            )
            return redirect('sale:adjustment_type_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'adjustment_type': adjustment_type})


class AdjustmentTypeDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        adjustment_type = get_object_or_404(SaleAdjustmentType, pk=pk)
        try:
            adjustment_type.delete()
        except ProtectedError:
            messages.error(request, 'This adjustment type is used in sales and cannot be deleted.')
        else:
            messages.success(request, 'Adjustment type deleted successfully.')
        return redirect('sale:adjustment_type_list')


# ---- sales -----------------------------------------------------------------

class SaleListView(AdminRequiredMixin, TemplateView):
    template_name = 'sale/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'statuses': Sale.Status.choices,
            'payment_statuses': Sale.PaymentStatus.choices,
            'filters': self.request.GET,
        })
        return context


class SaleDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-date'
    columns = [
        {'search_fields': ['date'], 'order_field': 'date'},
        {'search_fields': ['account__name'], 'order_field': 'account__name'},
        {'order_field': 'total_amount'},
        {'search_fields': ['status'], 'order_field': 'status'},
        {'search_fields': ['payment_status'], 'order_field': 'payment_status'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        params = self.request.GET
        queryset = Sale.objects.select_related('account')

        date_from = parse_date(params.get('date_from', ''))
        date_to = parse_date(params.get('date_to', ''))
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        if params.get('status') in Sale.Status.values:
            queryset = queryset.filter(status=params['status'])
        if params.get('payment_status') in Sale.PaymentStatus.values:
            queryset = queryset.filter(payment_status=params['payment_status'])
        return queryset

    def render_row(self, obj):
        return {
            'date': obj.date.strftime('%Y-%m-%d'),
            'account': obj.account.name,
            'total': f'{obj.total_amount} {obj.account.currency}',
            'status': format_html(
                '<span class="badge badge-{}">{}</span>', STATUS_BADGES[obj.status], obj.get_status_display(),
            ),
            'payment_status': format_html(
                '<span class="badge badge-{}">{}</span>',
                PAYMENT_BADGES[obj.payment_status], obj.get_payment_status_display(),
            ),
            'actions': render_to_string('sale/row_actions.html', {'sale': obj, 'editable': is_editable(obj)}),
        }


class SaleDetailView(AdminRequiredMixin, View):
    def get(self, request, pk):
        sale = get_object_or_404(Sale.objects.select_related('account'), pk=pk)
        lines = (
            sale.lines.select_related('lot__product', 'lot__purchase__warehouse', 'lot__transfer__to_warehouse')
            .prefetch_related('adjustments__adjustment_type')
            .order_by('id')
        )
        return render(request, 'sale/detail.html', {
            'sale': sale,
            'lines': lines,
            'sale_adjustments': sale.adjustments.filter(line__isnull=True).select_related('adjustment_type'),
            'editable': is_editable(sale),
            'is_sold': sale.status == Sale.Status.SOLD,
            'can_refund': sale.payment_status == Sale.PaymentStatus.RECEIVED,
            'status_badge': STATUS_BADGES[sale.status],
            'payment_badge': PAYMENT_BADGES[sale.payment_status],
        })


def lot_row(lot, price=None, extra=0):
    """One stock lot as the sale form's search shows it; `extra` is quantity a sale being edited already holds."""
    return {
        'id': lot.pk,
        'product': lot.product.name,
        'warehouse': lot.warehouse.name,
        'remaining': lot.remaining_quantity + extra,
        'purchase_price': str(lot.purchase_price),
        'sale_price': str(price if price is not None else lot.sale_price),
        'date': lot.created_at.strftime('%Y-%m-%d'),
    }


def lots_queryset():
    return StockLot.objects.select_related('product', 'purchase__warehouse', 'transfer__to_warehouse')


def held_by_sale(sale):
    """What an editable sale already holds: {lot id: (quantity, price)}."""
    return {line.lot_id: (line.quantity, line.sale_price) for line in sale.lines.all()}


class SaleFormView(AdminRequiredMixin, View):
    template_name = 'sale/form.html'

    def get_sale(self, pk):
        return get_object_or_404(Sale, pk=pk) if pk else None

    def blocked(self, request, sale):
        if sale is not None and not is_editable(sale):
            messages.error(request, 'Only a sold sale that was not refunded can be edited.')
            return redirect('sale:sale_detail', pk=sale.pk)
        return None

    @staticmethod
    def selected_lots(sale, payload):
        """The stock lots already on the form; the rest are searched on demand."""
        rows = payload.get('lines') if isinstance(payload, dict) else None
        ids = [parse_int(row.get('lot')) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        held = held_by_sale(sale) if sale else {}
        lots = lots_queryset().in_bulk([i for i in ids if i is not None])
        return [
            lot_row(lot, price=held[lot.pk][1] if lot.pk in held else None, extra=held[lot.pk][0] if lot.pk in held else 0)
            for lot in lots.values()
        ]

    def render_form(self, request, form, sale, payload, errors=()):
        return render(request, self.template_name, {
            'initial_lots': self.selected_lots(sale, payload),
            'form': form,
            'sale': sale,
            'errors': errors,
            'payload': payload,
            'adjustment_types': [
                {'id': t.pk, 'name': t.name, 'type': t.type}
                for t in SaleAdjustmentType.objects.order_by('name')
            ],
        })

    def get(self, request, pk=None):
        sale = self.get_sale(pk)
        if redirect_response := self.blocked(request, sale):
            return redirect_response
        payload = sale_to_payload(sale) if sale else {'lines': [], 'adjustments': []}
        return self.render_form(request, SaleHeaderForm(sale=sale), sale, payload)

    def post(self, request, pk=None):
        sale = self.get_sale(pk)
        if redirect_response := self.blocked(request, sale):
            return redirect_response

        form = SaleHeaderForm(request.POST, sale=sale)
        raw_payload = request.POST.get('payload', '')
        lines, adjustments, errors = parse_sale_payload(raw_payload)
        try:
            payload = json.loads(raw_payload)
        except ValueError:
            payload = {'lines': [], 'adjustments': []}
        if not isinstance(payload, dict):
            payload = {'lines': [], 'adjustments': []}

        if form.is_valid() and not errors:
            try:
                saved = save_sale(header=form.header(), lines=lines, adjustments=adjustments, sale=sale)
            except ValidationError as error:
                errors = error.messages
            else:
                messages.success(request, 'Sale updated successfully.' if sale else 'Sale added successfully.')
                return redirect('sale:sale_detail', pk=saved.pk)

        messages.error(request, 'Please fix the errors below.')
        return self.render_form(request, form, sale, payload, errors)


class SaleActionView(AdminRequiredMixin, View):
    """POST-only status change: runs a service function and goes back to the sale."""

    action = None
    success_message = ''

    def post(self, request, pk):
        sale = get_object_or_404(Sale, pk=pk)
        try:
            type(self).action(sale)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, self.success_message)
        return redirect('sale:sale_detail', pk=pk)


class SaleReturnView(SaleActionView):
    action = staticmethod(return_sale)
    success_message = 'Sale returned. The stock was added back to its lots.'


class SaleDamageView(SaleActionView):
    action = staticmethod(damage_sale)
    success_message = 'Sale marked as damaged.'


class SaleRefundView(SaleActionView):
    action = staticmethod(refund_sale)
    success_message = 'Sale refunded. The money was paid back from the account.'


class AvailableLotsView(AdminRequiredMixin, View):
    """Stock that can be sold, for a search-as-you-type dropdown, across every warehouse.

    Ten random lots until a search term is typed, then matching products ten
    per page. When editing a sale, the lots it already holds are included even
    if they are empty now, with their quantity added back and their saved price.
    """

    def get(self, request):
        held = {}
        sale_id = request.GET.get('sale', '')
        if sale_id.isdigit():
            sale = Sale.objects.filter(pk=int(sale_id)).first()
            if sale and is_editable(sale):
                held = held_by_sale(sale)

        lots = lots_queryset().filter(
            Q(pk__in=StockLot.objects.available().values('pk')) | Q(pk__in=list(held))
        )
        page, more = search_page(
            lots, request.GET.get('q'), request.GET.get('page'),
            'product__name', ('product__name', 'created_at', 'id'),
        )
        rows = [
            lot_row(lot, price=held[lot.pk][1] if lot.pk in held else None, extra=held[lot.pk][0] if lot.pk in held else 0)
            for lot in page
        ]
        rows.sort(key=lambda row: (row['product'].lower(), row['date'], row['id']))
        return JsonResponse({'lots': rows, 'more': more})
