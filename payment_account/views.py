from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.utils import delete_or_protect

from .forms import AccountForm
from .models import Account


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'


class AccountListView(AdminRequiredMixin, TemplateView):
    template_name = 'payment_account/list.html'


class AccountDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'search_fields': ['opening_balance'], 'order_field': 'opening_balance'},
        {'search_fields': ['currency'], 'order_field': 'currency'},
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return Account.objects.all()

    def render_row(self, obj):
        actions_html = render_to_string('payment_account/row_actions.html', {'account': obj})

        return {
            'name': obj.name,
            'opening_balance': str(obj.opening_balance),
            'currency': obj.get_currency_display(),
            'actions': actions_html,
        }


class AccountFormView(AdminRequiredMixin, View):
    template_name = 'payment_account/form.html'

    def get(self, request, pk=None):
        account = get_object_or_404(Account, pk=pk) if pk else None
        form = AccountForm(account=account)
        return render(request, self.template_name, {'form': form, 'account': account})

    def post(self, request, pk=None):
        account = get_object_or_404(Account, pk=pk) if pk else None
        is_new = account is None
        form = AccountForm(request.POST, account=account)
        if form.is_valid():
            form.save()
            messages.success(request, 'Account added successfully.' if is_new else 'Account updated successfully.')
            return redirect('payment_account:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'account': account})


class AccountDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        account = get_object_or_404(Account, pk=pk)
        delete_or_protect(request, account, 'Account deleted successfully.')
        return redirect('payment_account:list')
