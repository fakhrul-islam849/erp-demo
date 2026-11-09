from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.mixins import AdminRequiredMixin
from payment_account.models import Account

from .forms import CategoryForm, IncomeForm
from .models import Income, IncomeCategory
from .services import delete_income, save_income


# ---- categories ------------------------------------------------------------

class CategoryListView(AdminRequiredMixin, TemplateView):
    template_name = 'income/category/list.html'


class CategoryDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = 'name'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'order_field': 'created_at'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return IncomeCategory.objects.all()

    def render_row(self, obj):
        return {
            'name': obj.name,
            'created': obj.created_at.strftime('%Y-%m-%d'),
            'actions': render_to_string('income/category/row_actions.html', {'category': obj}),
        }


class CategoryFormView(AdminRequiredMixin, View):
    template_name = 'income/category/form.html'

    def get_object(self, pk):
        return get_object_or_404(IncomeCategory, pk=pk) if pk else None

    def get(self, request, pk=None):
        category = self.get_object(pk)
        return render(request, self.template_name, {'form': CategoryForm(instance=category), 'category': category})

    def post(self, request, pk=None):
        category = self.get_object(pk)
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(
                request, 'Category updated successfully.' if category else 'Category added successfully.',
            )
            return redirect('income:category_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'category': category})


class CategoryDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(IncomeCategory, pk=pk)
        try:
            category.delete()
        except ProtectedError:
            messages.error(request, 'This category has incomes and cannot be deleted.')
        else:
            messages.success(request, 'Category deleted successfully.')
        return redirect('income:category_list')


# ---- incomes ---------------------------------------------------------------

class IncomeListView(AdminRequiredMixin, TemplateView):
    template_name = 'income/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'categories': IncomeCategory.objects.order_by('name'),
            'accounts': Account.objects.order_by('name'),
            'filters': self.request.GET,
        })
        return context


class IncomeDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-date'
    columns = [
        {'search_fields': ['title'], 'order_field': 'title'},
        {'search_fields': ['category__name'], 'order_field': 'category__name'},
        {'search_fields': ['account__name'], 'order_field': 'account__name'},
        {'order_field': 'amount'},
        {'search_fields': ['date'], 'order_field': 'date'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        params = self.request.GET
        queryset = Income.objects.select_related('category', 'account')

        date_from = parse_date(params.get('date_from', ''))
        date_to = parse_date(params.get('date_to', ''))
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        for field in ('category', 'account'):
            value = params.get(field, '')
            if value.isdigit():
                queryset = queryset.filter(**{f'{field}_id': int(value)})
        return queryset

    def render_row(self, obj):
        return {
            'title': obj.title,
            'category': obj.category.name,
            'account': obj.account.name,
            'amount': f'{obj.amount} {obj.account.currency}',
            'date': obj.date.strftime('%Y-%m-%d'),
            'actions': render_to_string('income/row_actions.html', {'income': obj}),
        }


class IncomeFormView(AdminRequiredMixin, View):
    template_name = 'income/form.html'

    def get_income(self, pk):
        return get_object_or_404(Income, pk=pk) if pk else None

    def get(self, request, pk=None):
        income = self.get_income(pk)
        return render(request, self.template_name, {'form': IncomeForm(income=income), 'income': income})

    def post(self, request, pk=None):
        income = self.get_income(pk)
        form = IncomeForm(request.POST, income=income)
        if form.is_valid():
            try:
                save_income(values=form.values(), income=income)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Income updated successfully.' if income else 'Income added successfully.')
                return redirect('income:income_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'income': income})


class IncomeDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        income = get_object_or_404(Income, pk=pk)
        delete_income(income)
        messages.success(request, 'Income deleted. The amount was taken out of the account.')
        return redirect('income:income_list')
