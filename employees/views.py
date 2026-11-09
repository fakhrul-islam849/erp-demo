from django.template.loader import render_to_string

from common.datatables import BaseDatatableView

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import TemplateView
from django.contrib import messages

from .forms import EmployeeAccountForm, EmployeeCredentialsForm, EmployeeGeneralInfoForm

User = get_user_model()

class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'

class EmployeeListView(AdminRequiredMixin, TemplateView):
    template_name = 'employees/list.html'


class EmployeeAccountCreateView(AdminRequiredMixin, View):
    template_name = 'employees/account_form.html'

    def get(self, request):
        form = EmployeeAccountForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = EmployeeAccountForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Employee account created successfully.')
            return redirect('employees:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form})


class EmployeeInfoView(AdminRequiredMixin, View):
    template_name = 'employees/info_form.html'

    def get(self, request, uid):
        target_user = get_object_or_404(User, uid=uid)
        employee = getattr(target_user, 'employee', None)
        form = EmployeeGeneralInfoForm(user=target_user, employee=employee)
        return render(request, self.template_name, {'form': form, 'target_user': target_user, 'employee': employee})

    def post(self, request, uid):
        target_user = get_object_or_404(User, uid=uid)
        employee = getattr(target_user, 'employee', None)
        is_new = employee is None
        form = EmployeeGeneralInfoForm(request.POST, request.FILES, user=target_user, employee=employee)
        if form.is_valid():
            form.save()
            if is_new:
                messages.success(request, 'Employee information added successfully.')
            else:
                messages.success(request, 'Employee information updated successfully.')
            return redirect('employees:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'target_user': target_user, 'employee': employee})


class EmployeeCredentialsView(AdminRequiredMixin, View):
    template_name = 'employees/credentials_form.html'

    def get(self, request, uid):
        target_user = get_object_or_404(User, uid=uid)
        form = EmployeeCredentialsForm(user=target_user)
        return render(request, self.template_name, {'form': form, 'target_user': target_user})

    def post(self, request, uid):
        target_user = get_object_or_404(User, uid=uid)
        form = EmployeeCredentialsForm(request.POST, user=target_user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Credentials updated successfully.')
            return redirect('employees:list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'target_user': target_user})


class EmployeeDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-date_joined'
    columns = [
        {'search_fields': ['first_name', 'last_name', 'username'], 'order_field': 'first_name'},  # Name
        {'search_fields': ['username'], 'order_field': 'username'},                                # Username
        {'search_fields': ['email'], 'order_field': 'email'},                                      # Email
        {'search_fields': ['employee__designation'], 'order_field': 'employee__designation'},       # Designation
        {},  # Status - not searchable/orderable
        {},  # Actions - not searchable/orderable
    ]

    def get_queryset(self):
        return User.objects.filter(user_type=User.UserType.EMPLOYEE).select_related('employee')

    def render_row(self, obj):
        employee = getattr(obj, 'employee', None)

        if obj.is_active:
            status_html = '<span class="badge badge-success">Active</span>'
        else:
            status_html = '<span class="badge badge-danger">Inactive</span>'

        actions_html = render_to_string('employees/row_actions.html', {
            'target_user': obj,
            'has_profile': employee is not None,
        })

        return {
            'name': obj.get_full_name() or obj.username,
            'username': obj.username,
            'email': obj.email,
            'designation': employee.designation if employee else '—',
            'status': status_html,
            'actions': actions_html,
        }

class EmployeeDetailView(AdminRequiredMixin, View):
    template_name = 'employees/detail.html'

    def get(self, request, uid):
        target_user = get_object_or_404(User, uid=uid)
        employee = getattr(target_user, 'employee', None)
        return render(request, self.template_name, {'target_user': target_user, 'employee': employee})