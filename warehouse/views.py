from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.utils import delete_or_protect

from .forms import WarehouseForm
from .models import Warehouse


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'


class WarehouseListView(AdminRequiredMixin, TemplateView):
    template_name = 'warehouse/list.html'


class WarehouseDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'search_fields': ['marketplace_name'], 'order_field': 'marketplace_name'},
        {'search_fields': ['marketplace_location'], 'order_field': 'marketplace_location'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return Warehouse.objects.all()

    def render_row(self, obj):
        actions_html = render_to_string('warehouse/row_actions.html', {'warehouse': obj})

        return {
            'name': obj.name,
            'marketplace_name': obj.marketplace_name,
            'marketplace_location': obj.marketplace_location,
            'actions': actions_html,
        }


class WarehouseFormView(AdminRequiredMixin, View):
    template_name = 'warehouse/form.html'

    def get(self, request, pk=None):
        warehouse = get_object_or_404(Warehouse, pk=pk) if pk else None
        form = WarehouseForm(warehouse=warehouse)
        return render(request, self.template_name, {'form': form, 'warehouse': warehouse})

    def post(self, request, pk=None):
        warehouse = get_object_or_404(Warehouse, pk=pk) if pk else None
        is_new = warehouse is None
        form = WarehouseForm(request.POST, warehouse=warehouse)
        if form.is_valid():
            form.save()
            if is_new:
                messages.success(request, 'Warehouse added successfully.')
            else:
                messages.success(request, 'Warehouse updated successfully.')
            return redirect('warehouse:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'warehouse': warehouse})


class WarehouseDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        warehouse = get_object_or_404(Warehouse, pk=pk)
        delete_or_protect(request, warehouse, 'Warehouse deleted successfully.')
        return redirect('warehouse:list')
