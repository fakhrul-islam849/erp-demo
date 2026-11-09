import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from product.models import Product
from supplier.models import Supplier
from warehouse.models import Warehouse

from .forms import AdjustmentTypeForm, PurchaseHeaderForm, parse_int, parse_payload, purchase_to_payload
from .models import Purchase, PurchaseAdjustmentType, StockLot
from .services import cancel_purchase, is_locked, save_purchase


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'


class AdjustmentTypeListView(AdminRequiredMixin, TemplateView):
    template_name = 'purchase/adjustment_type/list.html'


class AdjustmentTypeDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'search_fields': ['type'], 'order_field': 'type'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return PurchaseAdjustmentType.objects.all()

    def render_row(self, obj):
        actions_html = render_to_string(
            'purchase/adjustment_type/row_actions.html', {'adjustment_type': obj},
        )

        return {
            'name': obj.name,
            'type': obj.get_type_display(),
            'actions': actions_html,
        }


class AdjustmentTypeFormView(AdminRequiredMixin, View):
    template_name = 'purchase/adjustment_type/form.html'

    def get(self, request, pk=None):
        adjustment_type = get_object_or_404(PurchaseAdjustmentType, pk=pk) if pk else None
        form = AdjustmentTypeForm(adjustment_type=adjustment_type)
        return render(request, self.template_name, {'form': form, 'adjustment_type': adjustment_type})

    def post(self, request, pk=None):
        adjustment_type = get_object_or_404(PurchaseAdjustmentType, pk=pk) if pk else None
        is_new = adjustment_type is None
        form = AdjustmentTypeForm(request.POST, adjustment_type=adjustment_type)
        if form.is_valid():
            form.save()
            if is_new:
                messages.success(request, 'Adjustment type added successfully.')
            else:
                messages.success(request, 'Adjustment type updated successfully.')
            return redirect('purchase:adjustment_type_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'adjustment_type': adjustment_type})


class AdjustmentTypeDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        adjustment_type = get_object_or_404(PurchaseAdjustmentType, pk=pk)
        try:
            adjustment_type.delete()
        except ProtectedError:
            messages.error(request, 'This adjustment type is used in purchases and cannot be deleted.')
        else:
            messages.success(request, 'Adjustment type deleted successfully.')
        return redirect('purchase:adjustment_type_list')


STATUS_BADGES = {
    Purchase.Status.PENDING: 'warning',
    Purchase.Status.PAID: 'success',
    Purchase.Status.CANCELLED: 'secondary',
}


class PurchaseListView(AdminRequiredMixin, TemplateView):
    template_name = 'purchase/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'warehouses': Warehouse.objects.order_by('name'),
            'suppliers': Supplier.objects.order_by('name'),
            'statuses': Purchase.Status.choices,
            'filters': self.request.GET,
        })
        return context


class PurchaseDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-date'
    columns = [
        {'search_fields': ['date'], 'order_field': 'date'},
        {'search_fields': ['supplier__name'], 'order_field': 'supplier__name'},
        {'search_fields': ['warehouse__name'], 'order_field': 'warehouse__name'},
        {'search_fields': ['account__name'], 'order_field': 'account__name'},
        {'order_field': 'total_amount'},
        {'search_fields': ['status'], 'order_field': 'status'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        params = self.request.GET
        queryset = Purchase.objects.select_related('supplier', 'warehouse', 'account')

        date_from = parse_date(params.get('date_from', ''))
        date_to = parse_date(params.get('date_to', ''))
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        for field in ('warehouse', 'supplier'):
            value = params.get(field, '')
            if value.isdigit():
                queryset = queryset.filter(**{f'{field}_id': int(value)})
        if params.get('status') in Purchase.Status.values:
            queryset = queryset.filter(status=params['status'])
        return queryset

    def render_row(self, obj):
        return {
            'date': obj.date.strftime('%Y-%m-%d'),
            'supplier': obj.supplier.name,
            'warehouse': obj.warehouse.name,
            'account': obj.account.name,
            'total': f'{obj.total_amount} {obj.account.currency}',
            'status': format_html(
                '<span class="badge badge-{}">{}</span>',
                STATUS_BADGES[obj.status], obj.get_status_display(),
            ),
            'actions': render_to_string('purchase/row_actions.html', {'purchase': obj}),
        }


class PurchaseDetailView(AdminRequiredMixin, View):
    def get(self, request, pk):
        purchase = get_object_or_404(
            Purchase.objects.select_related('supplier', 'warehouse', 'account'), pk=pk,
        )
        lots = purchase.lots.select_related('product').prefetch_related('adjustments__adjustment_type')
        return render(request, 'purchase/detail.html', {
            'purchase': purchase,
            'lots': lots,
            'header_adjustments': purchase.adjustments.filter(lot__isnull=True).select_related('adjustment_type'),
            'editable': purchase.status != Purchase.Status.CANCELLED and not is_locked(purchase),
            'badge': STATUS_BADGES[purchase.status],
        })


class PurchaseFormView(AdminRequiredMixin, View):
    template_name = 'purchase/form.html'

    def get_purchase(self, pk):
        return get_object_or_404(Purchase, pk=pk) if pk else None

    def blocked(self, request, purchase):
        if purchase is None:
            return None
        if purchase.status == Purchase.Status.CANCELLED:
            messages.error(request, 'A cancelled purchase cannot be edited.')
        elif is_locked(purchase):
            messages.error(request, 'Stock from this purchase has already been used, so it cannot be edited.')
        else:
            return None
        return redirect('purchase:purchase_detail', pk=purchase.pk)

    @staticmethod
    def selected_products(payload):
        """Names of the products already on the form; the rest are searched on demand."""
        rows = payload.get('lines') if isinstance(payload, dict) else None
        ids = [parse_int(row.get('product')) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        products = Product.objects.in_bulk([i for i in ids if i is not None])
        return [{'id': p.pk, 'name': p.name} for p in products.values()]

    def render_form(self, request, form, purchase, payload, errors=()):
        return render(request, self.template_name, {
            'form': form,
            'purchase': purchase,
            'errors': errors,
            'payload': payload,
            'products': self.selected_products(payload),
            'adjustment_types': [
                {'id': t.pk, 'name': t.name, 'type': t.type}
                for t in PurchaseAdjustmentType.objects.order_by('name')
            ],
            'payload_json': json.dumps(payload),
        })

    def get(self, request, pk=None):
        purchase = self.get_purchase(pk)
        if redirect_response := self.blocked(request, purchase):
            return redirect_response
        payload = purchase_to_payload(purchase) if purchase else {'lines': [], 'adjustments': []}
        return self.render_form(request, PurchaseHeaderForm(purchase=purchase), purchase, payload)

    def post(self, request, pk=None):
        purchase = self.get_purchase(pk)
        if redirect_response := self.blocked(request, purchase):
            return redirect_response

        form = PurchaseHeaderForm(request.POST, request.FILES, purchase=purchase)
        raw_payload = request.POST.get('payload', '')
        lines, adjustments, errors = parse_payload(raw_payload)
        try:
            payload = json.loads(raw_payload)
        except ValueError:
            payload = {'lines': [], 'adjustments': []}

        if form.is_valid() and not errors:
            try:
                saved = save_purchase(
                    header=form.header(), lines=lines, adjustments=adjustments, purchase=purchase,
                )
            except ValidationError as error:
                errors = error.messages
            else:
                messages.success(
                    request, 'Purchase updated successfully.' if purchase else 'Purchase added successfully.',
                )
                return redirect('purchase:purchase_detail', pk=saved.pk)

        messages.error(request, 'Please fix the errors below.')
        return self.render_form(request, form, purchase, payload, errors)


class PurchaseCancelView(AdminRequiredMixin, View):
    def post(self, request, pk):
        purchase = get_object_or_404(Purchase, pk=pk)
        try:
            cancel_purchase(purchase)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, 'Purchase cancelled.')
        return redirect('purchase:purchase_detail', pk=pk)


class SuggestPriceView(AdminRequiredMixin, View):
    """Latest purchase/sale price for a product, preferring the same supplier."""

    def get(self, request):
        product_id = request.GET.get('product', '')
        supplier_id = request.GET.get('supplier', '')
        if not product_id.isdigit():
            return JsonResponse({'purchase_price': None, 'sale_price': None, 'source': None})

        lots = (
            StockLot.objects
            .filter(product_id=int(product_id), purchase__isnull=False)
            .exclude(purchase__status=Purchase.Status.CANCELLED)
            .order_by('-purchase__date', '-id')
        )
        source = 'supplier'
        lot = lots.filter(purchase__supplier_id=int(supplier_id)).first() if supplier_id.isdigit() else None
        if lot is None:
            source = 'product'
            lot = lots.first()
        if lot is None:
            return JsonResponse({'purchase_price': None, 'sale_price': None, 'source': None})
        return JsonResponse({
            'purchase_price': str(lot.purchase_price.quantize(Decimal('0.01'))),
            'sale_price': str(lot.sale_price),
            'source': source,
        })
