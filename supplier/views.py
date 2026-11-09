from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.utils import delete_or_protect

from .forms import SupplierForm
from .models import Supplier


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'


class SupplierListView(AdminRequiredMixin, TemplateView):
    template_name = 'supplier/list.html'


class SupplierDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'search_fields': ['phone'], 'order_field': 'phone'},
        {'search_fields': ['email'], 'order_field': 'email'},
        {'search_fields': ['country'], 'order_field': 'country'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return Supplier.objects.all()

    def render_row(self, obj):
        actions_html = render_to_string('supplier/row_actions.html', {'supplier': obj})

        return {
            'name': obj.name,
            'phone': obj.phone,
            'email': obj.email,
            'country': obj.get_country_display(),
            'actions': actions_html,
        }


class SupplierFormView(AdminRequiredMixin, View):
    template_name = 'supplier/form.html'

    def get(self, request, pk=None):
        supplier = get_object_or_404(Supplier, pk=pk) if pk else None
        form = SupplierForm(supplier=supplier)
        return render(request, self.template_name, {'form': form, 'supplier': supplier})

    def post(self, request, pk=None):
        supplier = get_object_or_404(Supplier, pk=pk) if pk else None
        is_new = supplier is None
        form = SupplierForm(request.POST, supplier=supplier)
        if form.is_valid():
            form.save()
            if is_new:
                messages.success(request, 'Supplier added successfully.')
            else:
                messages.success(request, 'Supplier updated successfully.')
            return redirect('supplier:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'supplier': supplier})


class SupplierDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        delete_or_protect(request, supplier, 'Supplier deleted successfully.')
        return redirect('supplier:list')
