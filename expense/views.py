from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.mixins import AdminRequiredMixin
from payment_account.models import Account

from .forms import CategoryForm, ExpenseForm
from .models import Expense, ExpenseCategory
from .services import delete_expense, save_expense


# ---- categories ------------------------------------------------------------

class CategoryListView(AdminRequiredMixin, TemplateView):
    template_name = 'expense/category/list.html'


class CategoryDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = 'name'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'order_field': 'created_at'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return ExpenseCategory.objects.all()

    def render_row(self, obj):
        return {
            'name': obj.name,
            'created': obj.created_at.strftime('%Y-%m-%d'),
            'actions': render_to_string('expense/category/row_actions.html', {'category': obj}),
        }


class CategoryFormView(AdminRequiredMixin, View):
    template_name = 'expense/category/form.html'

    def get_object(self, pk):
        return get_object_or_404(ExpenseCategory, pk=pk) if pk else None

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
            return redirect('expense:category_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'category': category})


class CategoryDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(ExpenseCategory, pk=pk)
        try:
            category.delete()
        except ProtectedError:
            messages.error(request, 'This category has expenses and cannot be deleted.')
        else:
            messages.success(request, 'Category deleted successfully.')
        return redirect('expense:category_list')


# ---- expenses --------------------------------------------------------------

class ExpenseListView(AdminRequiredMixin, TemplateView):
    template_name = 'expense/list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'categories': ExpenseCategory.objects.order_by('name'),
            'accounts': Account.objects.order_by('name'),
            'filters': self.request.GET,
        })
        return context


class ExpenseDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-date'
    columns = [
        {'search_fields': ['title'], 'order_field': 'title'},
        {'search_fields': ['category__name'], 'order_field': 'category__name'},
        {'search_fields': ['account__name'], 'order_field': 'account__name'},
        {'order_field': 'amount'},
        {'search_fields': ['date'], 'order_field': 'date'},
        {},  # Attachment - not searchable/orderable
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        params = self.request.GET
        queryset = Expense.objects.select_related('category', 'account')

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
        if obj.attachment:
            attachment = format_html(
                '<a href="{}" target="_blank" rel="noopener"><i class="mdi mdi-paperclip"></i> View</a>',
                obj.attachment.url,
            )
        else:
            attachment = '—'
        return {
            'title': obj.title,
            'category': obj.category.name,
            'account': obj.account.name,
            'amount': f'{obj.amount} {obj.account.currency}',
            'date': obj.date.strftime('%Y-%m-%d'),
            'attachment': attachment,
            'actions': render_to_string('expense/row_actions.html', {'expense': obj}),
        }


class ExpenseFormView(AdminRequiredMixin, View):
    template_name = 'expense/form.html'

    def get_expense(self, pk):
        return get_object_or_404(Expense, pk=pk) if pk else None

    def get(self, request, pk=None):
        expense = self.get_expense(pk)
        return render(request, self.template_name, {'form': ExpenseForm(expense=expense), 'expense': expense})

    def post(self, request, pk=None):
        expense = self.get_expense(pk)
        form = ExpenseForm(request.POST, request.FILES, expense=expense)
        if form.is_valid():
            try:
                save_expense(values=form.values(), expense=expense)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(
                    request, 'Expense updated successfully.' if expense else 'Expense added successfully.',
                )
                return redirect('expense:expense_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'expense': expense})


class ExpenseDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        delete_expense(expense)
        messages.success(request, 'Expense deleted. The amount was put back in the account.')
        return redirect('expense:expense_list')
