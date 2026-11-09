from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.utils import delete_or_protect

from .forms import CategoryForm, PadForm, SignatureForm
from .models import Category, Pad, ShareLink
from .services import generate_final_pdf


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'


# ---------- Category ----------

class CategoryListView(AdminRequiredMixin, TemplateView):
    template_name = 'company_pad/category_list.html'


class CategoryDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {},  # Actions
    ]

    def get_queryset(self):
        return Category.objects.all()

    def render_row(self, obj):
        actions_html = render_to_string('company_pad/category_row_actions.html', {'category': obj})
        return {'name': obj.name, 'actions': actions_html}


class CategoryFormView(AdminRequiredMixin, View):
    template_name = 'company_pad/category_form.html'

    def get(self, request, pk=None):
        category = get_object_or_404(Category, pk=pk) if pk else None
        form = CategoryForm(category=category)
        return render(request, self.template_name, {'form': form, 'category': category})

    def post(self, request, pk=None):
        category = get_object_or_404(Category, pk=pk) if pk else None
        is_new = category is None
        form = CategoryForm(request.POST, category=category)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category added successfully.' if is_new else 'Category updated successfully.')
            return redirect('company_pad:category_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'category': category})


class CategoryDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        delete_or_protect(request, category, 'Category deleted successfully.')
        return redirect('company_pad:category_list')


# ---------- Pad ----------

class PadAccessMixin(LoginRequiredMixin):
    def get_pad_queryset(self):
        user = self.request.user
        if user.user_type == 'admin':
            return Pad.objects.all()
        return Pad.objects.filter(party_b_employee=user).exclude(status=Pad.Status.DRAFT)


class PadListView(PadAccessMixin, TemplateView):
    template_name = 'company_pad/pad_list.html'


class PadDatatableView(PadAccessMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['title'], 'order_field': 'title'},
        {'search_fields': ['category__name'], 'order_field': 'category__name'},
        {},  # Party B
        {'order_field': 'status'},
        {'order_field': 'created_at'},
        {},  # Actions
    ]

    def get_queryset(self):
        return self.get_pad_queryset().select_related('category', 'party_b_employee')

    def render_row(self, obj):
        actions_html = render_to_string('company_pad/pad_row_actions.html', {'pad': obj}, request=self.request)
        return {
            'title': obj.title,
            'category': obj.category.name,
            'party_b': obj.party_b_display_name(),
            'status': obj.get_status_display(),
            'created_at': obj.created_at.strftime('%Y-%m-%d'),
            'actions': actions_html,
        }


class PadDetailView(PadAccessMixin, View):
    template_name = 'company_pad/pad_detail.html'

    def get(self, request, pk):
        pad = get_object_or_404(self.get_pad_queryset(), pk=pk)
        return render(request, self.template_name, {'pad': pad})


class PadDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        try:
            pad.delete()
            messages.success(request, 'Pad deleted successfully.')
        except ValueError as e:
            messages.error(request, str(e))
        return redirect('company_pad:pad_list')


class PadReleaseView(AdminRequiredMixin, View):
    def post(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        if pad.status != Pad.Status.DRAFT:
            messages.error(request, 'This pad has already been released.')
            return redirect('company_pad:pad_detail', pk=pad.pk)
        pad.status = Pad.Status.AWAITING_SIGNATURE
        pad.save()
        messages.success(request, 'Pad released for signing.')
        return redirect('company_pad:pad_detail', pk=pad.pk)


class PadRevertToDraftView(AdminRequiredMixin, View):
    def post(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        if pad.status != Pad.Status.AWAITING_SIGNATURE or pad.signed_by_party_b_at:
            messages.error(request, 'This pad can no longer be reverted to draft.')
            return redirect('company_pad:pad_detail', pk=pad.pk)
        pad.status = Pad.Status.DRAFT
        pad.signed_by_admin_name = None
        pad.signed_by_admin_at = None
        pad.signed_by_party_b_name = None
        pad.signed_by_party_b_at = None
        pad.save()
        messages.success(request, 'Pad reverted to draft. You can now edit it.')
        return redirect('company_pad:pad_detail', pk=pad.pk)


class PadFormView(AdminRequiredMixin, View):
    template_name = 'company_pad/pad_form.html'

    def get(self, request, pk=None):
        pad = get_object_or_404(Pad, pk=pk) if pk else None
        form = PadForm(pad=pad)
        return render(request, self.template_name, {'form': form, 'pad': pad})

    def post(self, request, pk=None):
        pad = get_object_or_404(Pad, pk=pk) if pk else None
        is_new = pad is None
        form = PadForm(request.POST, request.FILES, pad=pad)
        if form.is_valid():
            form.save(created_by=request.user)
            messages.success(request, 'Pad created successfully.' if is_new else 'Pad updated successfully.')
            return redirect('company_pad:pad_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'pad': pad})


class PadAdminSignView(AdminRequiredMixin, View):
    template_name = 'company_pad/pad_sign.html'

    def _check_signable(self, request, pad):
        if pad.status != Pad.Status.AWAITING_SIGNATURE:
            messages.error(request, 'This pad has not been released for signing yet.')
            return False
        if pad.signed_by_admin_at:
            messages.error(request, 'You have already signed this pad.')
            return False
        return True

    def get(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        if not self._check_signable(request, pad):
            return redirect('company_pad:pad_detail', pk=pad.pk)
        form = SignatureForm(initial={'name': request.user.get_full_name() or request.user.username})
        return render(request, self.template_name, {'form': form, 'pad': pad, 'role_label': 'Admin'})

    def post(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        if not self._check_signable(request, pad):
            return redirect('company_pad:pad_detail', pk=pad.pk)
        form = SignatureForm(request.POST)
        if form.is_valid():
            pad.signed_by_admin_name = form.cleaned_data['name']
            pad.signed_by_admin_at = timezone.now()
            if pad.signed_by_party_b_at:
                pad.status = Pad.Status.SIGNED
                generate_final_pdf(pad)
            pad.save()
            messages.success(request, 'Signed successfully.')
            return redirect('company_pad:pad_detail', pk=pad.pk)
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'pad': pad, 'role_label': 'Admin'})


class PadEmployeeSignView(LoginRequiredMixin, View):
    template_name = 'company_pad/pad_sign.html'

    def _check_signable(self, request, pad):
        if pad.party_b_type != Pad.PartyBType.EMPLOYEE or pad.party_b_employee_id != request.user.id:
            raise Http404
        if pad.status != Pad.Status.AWAITING_SIGNATURE:
            messages.error(request, 'This pad is not ready for your signature yet.')
            return False
        if pad.signed_by_party_b_at:
            messages.error(request, 'You have already signed this pad.')
            return False
        return True

    def get(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        if not self._check_signable(request, pad):
            return redirect('company_pad:pad_detail', pk=pad.pk)
        form = SignatureForm(initial={'name': request.user.get_full_name() or request.user.username})
        return render(request, self.template_name, {'form': form, 'pad': pad, 'role_label': 'Employee'})

    def post(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        if not self._check_signable(request, pad):
            return redirect('company_pad:pad_detail', pk=pad.pk)
        form = SignatureForm(request.POST)
        if form.is_valid():
            pad.signed_by_party_b_name = form.cleaned_data['name']
            pad.signed_by_party_b_at = timezone.now()
            if pad.signed_by_admin_at:
                pad.status = Pad.Status.SIGNED
                generate_final_pdf(pad)
            pad.save()
            messages.success(request, 'Signed successfully.')
            return redirect('company_pad:pad_detail', pk=pad.pk)
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'pad': pad, 'role_label': 'Employee'})


class PadGenerateShareLinkView(AdminRequiredMixin, View):
    def post(self, request, pk):
        pad = get_object_or_404(Pad, pk=pk)
        ShareLink.objects.create(
            pad=pad,
            expires_at=timezone.now() + timedelta(days=7),
            created_by=request.user,
        )
        messages.success(request, 'Share link generated.')
        return redirect('company_pad:pad_detail', pk=pad.pk)


class PadPublicView(View):
    def get(self, request, token):
        link = get_object_or_404(ShareLink, token=token)
        if not link.is_valid():
            return render(request, 'company_pad/pad_public_invalid.html', status=410)
        pad = link.pad
        if pad.party_b_type == Pad.PartyBType.EXTERNAL and pad.status == Pad.Status.AWAITING_SIGNATURE and not pad.signed_by_party_b_at:
            form = SignatureForm(initial={'name': pad.party_b_name or ''})
            return render(request, 'company_pad/pad_public_sign.html', {'pad': pad, 'form': form, 'token': token})
        return render(request, 'company_pad/pad_public_view.html', {'pad': pad})

    def post(self, request, token):
        link = get_object_or_404(ShareLink, token=token)
        if not link.is_valid():
            return render(request, 'company_pad/pad_public_invalid.html', status=410)
        pad = link.pad
        if not (pad.party_b_type == Pad.PartyBType.EXTERNAL and pad.status == Pad.Status.AWAITING_SIGNATURE and not pad.signed_by_party_b_at):
            messages.error(request, 'This document is not available for signing right now.')
            return redirect('company_pad:pad_public', token=token)
        form = SignatureForm(request.POST)
        if form.is_valid():
            pad.signed_by_party_b_name = form.cleaned_data['name']
            pad.signed_by_party_b_at = timezone.now()
            if pad.signed_by_admin_at:
                pad.status = Pad.Status.SIGNED
                generate_final_pdf(pad)
            pad.save()
            messages.success(request, 'Signed successfully.')
            return redirect('company_pad:pad_public', token=token)
        return render(request, 'company_pad/pad_public_sign.html', {'pad': pad, 'form': form, 'token': token})