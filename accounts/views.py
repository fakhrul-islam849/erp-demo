from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from .forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

class AccountSettingsView(LoginRequiredMixin, View):
    template_name = 'accounts/settings.html'

    def get(self, request):
        form = PasswordChangeForm(user=request.user)
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password updated successfully.')
            return redirect('accounts:settings')
        return render(request, self.template_name, {'form': form})
