import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
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
from purchase.models import PurchaseAdjustmentType, StockLot
from warehouse.models import Warehouse

from .forms import TransferHeaderForm, parse_int, parse_transfer_payload, transfer_to_payload
from .models import Transfer
from .services import cancel_transfer, confirm_transfer, save_transfer

STATUS_BADGES = {
    Transfer.Status.IN_TRANSIT: 'warning',
    Transfer.Status.CONFIRMED: 'success',
    Transfer.Status.CANCELLED: 'secondary',
}


class TransferListView(AdminRequiredMixin, TemplateView):
    template_name = 'transfer/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'warehouses': Warehouse.objects.order_by('name'),
            'statuses': Transfer.Status.choices,
            'filters': self.request.GET,
        })
        return context


class TransferDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-date'
    columns = [
        {'search_fields': ['date'], 'order_field': 'date'},
        {'search_fields': ['from_warehouse__name'], 'order_field': 'from_warehouse__name'},
        {'search_fields': ['to_warehouse__name'], 'order_field': 'to_warehouse__name'},
        {'search_fields': ['status'], 'order_field': 'status'},
        {},  # Net cost - computed from two columns
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        params = self.request.GET
        queryset = Transfer.objects.select_related('from_warehouse', 'to_warehouse', 'account')

        date_from = parse_date(params.get('date_from', ''))
        date_to = parse_date(params.get('date_to', ''))
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        for field in ('from_warehouse', 'to_warehouse'):
            value = params.get(field, '')
            if value.isdigit():
                queryset = queryset.filter(**{f'{field}_id': int(value)})
        if params.get('status') in Transfer.Status.values:
            queryset = queryset.filter(status=params['status'])
        return queryset

    def render_row(self, obj):
        net_cost = obj.net_cost
        return {
            'date': obj.date.strftime('%Y-%m-%d'),
            'from': obj.from_warehouse.name,
            'to': obj.to_warehouse.name,
            'status': format_html(
                '<span class="badge badge-{}">{}</span>',
                STATUS_BADGES[obj.status], obj.get_status_display(),
            ),
            'net_cost': f'{net_cost} {obj.account.currency}' if obj.account_id and net_cost else '—',
            'actions': render_to_string('transfer/row_actions.html', {'transfer': obj}),
        }


class TransferDetailView(AdminRequiredMixin, View):
    def get(self, request, pk):
        transfer = get_object_or_404(
            Transfer.objects.select_related('from_warehouse', 'to_warehouse', 'account'), pk=pk,
        )
        lots = (
            transfer.lots.select_related('product', 'source_lot')
            .prefetch_related('adjustments__adjustment_type')
            .order_by('id')
        )
        return render(request, 'transfer/detail.html', {
            'transfer': transfer,
            'lots': lots,
            'header_adjustments': transfer.adjustments.filter(lot__isnull=True).select_related('adjustment_type'),
            'in_transit': transfer.status == Transfer.Status.IN_TRANSIT,
            'badge': STATUS_BADGES[transfer.status],
        })


class TransferFormView(AdminRequiredMixin, View):
    template_name = 'transfer/form.html'

    def get_transfer(self, pk):
        return get_object_or_404(Transfer, pk=pk) if pk else None

    def blocked(self, request, transfer):
        if transfer is not None and transfer.status != Transfer.Status.IN_TRANSIT:
            messages.error(request, 'Only a transfer that is in transit can be edited.')
            return redirect('transfer:transfer_detail', pk=transfer.pk)
        return None

    @staticmethod
    def selected_lots(transfer, payload):
        """The stock lots already on the form; the rest are searched on demand."""
        rows = payload.get('lines') if isinstance(payload, dict) else None
        ids = [parse_int(row.get('source_lot')) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        reserved = reserved_by_transfer(transfer) if transfer else {}
        lots = StockLot.objects.select_related('product').in_bulk([i for i in ids if i is not None])
        return [lot_row(lot, reserved.get(lot.pk, 0)) for lot in lots.values()]

    def render_form(self, request, form, transfer, payload, errors=()):
        return render(request, self.template_name, {
            'initial_lots': self.selected_lots(transfer, payload),
            'form': form,
            'transfer': transfer,
            'errors': errors,
            'payload': payload,
            'adjustment_types': [
                {'id': t.pk, 'name': t.name, 'type': t.type}
                for t in PurchaseAdjustmentType.objects.order_by('name')
            ],
        })

    def get(self, request, pk=None):
        transfer = self.get_transfer(pk)
        if redirect_response := self.blocked(request, transfer):
            return redirect_response
        payload = transfer_to_payload(transfer) if transfer else {'lines': [], 'adjustments': []}
        return self.render_form(request, TransferHeaderForm(transfer=transfer), transfer, payload)

    def post(self, request, pk=None):
        transfer = self.get_transfer(pk)
        if redirect_response := self.blocked(request, transfer):
            return redirect_response

        form = TransferHeaderForm(request.POST, transfer=transfer)
        raw_payload = request.POST.get('payload', '')
        lines, adjustments, errors = parse_transfer_payload(raw_payload)
        try:
            payload = json.loads(raw_payload)
        except ValueError:
            payload = {'lines': [], 'adjustments': []}
        if not isinstance(payload, dict):
            payload = {'lines': [], 'adjustments': []}

        if form.is_valid() and not errors:
            try:
                saved = save_transfer(
                    header=form.header(), lines=lines, adjustments=adjustments, transfer=transfer,
                )
            except ValidationError as error:
                errors = error.messages
            else:
                messages.success(
                    request, 'Transfer updated successfully.' if transfer else 'Transfer sent successfully.',
                )
                return redirect('transfer:transfer_detail', pk=saved.pk)

        messages.error(request, 'Please fix the errors below.')
        return self.render_form(request, form, transfer, payload, errors)


class TransferConfirmView(AdminRequiredMixin, View):
    def post(self, request, pk):
        transfer = get_object_or_404(Transfer, pk=pk)
        try:
            confirm_transfer(transfer)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, 'Transfer confirmed. The stock is now available in the new warehouse.')
        return redirect('transfer:transfer_detail', pk=pk)


class TransferCancelView(AdminRequiredMixin, View):
    def post(self, request, pk):
        transfer = get_object_or_404(Transfer, pk=pk)
        try:
            cancel_transfer(transfer)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, 'Transfer cancelled. The stock was returned to the source warehouse.')
        return redirect('transfer:transfer_detail', pk=pk)


def lot_row(lot, reserved=0):
    return {
        'id': lot.pk,
        'product': lot.product.name,
        'remaining': lot.remaining_quantity + reserved,
        'landed_cost': str(lot.landed_cost),
        'sale_price': str(lot.sale_price),
        'date': lot.created_at.strftime('%Y-%m-%d'),
    }


def reserved_by_transfer(transfer):
    """Quantity this transfer has taken out of each source lot."""
    reserved = {}
    for lot in transfer.lots.all():
        reserved[lot.source_lot_id] = reserved.get(lot.source_lot_id, 0) + lot.quantity
    return reserved


class AvailableLotsView(AdminRequiredMixin, View):
    """Stock that can be transferred out of a warehouse, for a search-as-you-type dropdown.

    Ten random lots until a search term is typed, then matching products ten
    per page. When editing a transfer that is still in transit, its own
    reserved quantities are added back so its saved lines can be shown and
    changed.
    """

    def get(self, request):
        warehouse_id = request.GET.get('warehouse', '')
        if not warehouse_id.isdigit():
            return JsonResponse({'lots': [], 'more': False})
        warehouse = get_object_or_404(Warehouse, pk=int(warehouse_id))

        reserved = {}
        transfer_id = request.GET.get('transfer', '')
        if transfer_id.isdigit():
            transfer = Transfer.objects.filter(
                pk=int(transfer_id), status=Transfer.Status.IN_TRANSIT, from_warehouse=warehouse,
            ).first()
            if transfer:
                reserved = reserved_by_transfer(transfer)

        lots = StockLot.objects.filter(
            Q(pk__in=StockLot.objects.available(warehouse).values('pk')) | Q(pk__in=list(reserved))
        ).select_related('product')
        page, more = search_page(
            lots, request.GET.get('q'), request.GET.get('page'),
            'product__name', ('product__name', 'created_at', 'id'),
        )
        rows = [lot_row(lot, reserved.get(lot.pk, 0)) for lot in page]
        rows.sort(key=lambda row: (row['product'].lower(), row['date'], row['id']))
        return JsonResponse({'lots': rows, 'more': more})
