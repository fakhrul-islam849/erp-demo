from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render
from django.views import View

from .forms import CompanyForm
from .models import Company


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'


class CompanyDetailView(AdminRequiredMixin, View):
    template_name = 'company/detail.html'

    def get(self, request):
        company = Company.load()
        if company is None:
            return redirect('company:form')
        return render(request, self.template_name, {'company': company})


class CompanyFormView(AdminRequiredMixin, View):
    template_name = 'company/form.html'

    def get(self, request):
        company = Company.load()
        form = CompanyForm(company=company)
        return render(request, self.template_name, {'form': form, 'company': company})

    def post(self, request):
        company = Company.load()
        is_new = company is None
        form = CompanyForm(request.POST, request.FILES, company=company)
        if form.is_valid():
            form.save()
            if is_new:
                messages.success(request, 'Company information added successfully.')
            else:
                messages.success(request, 'Company information updated successfully.')
            return redirect('company:detail')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'company': company})