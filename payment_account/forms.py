from django import forms
from common.constants import CURRENCY_CHOICES

from .models import Account

class AccountForm(forms.Form):
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    opening_balance = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
    )
    currency = forms.ChoiceField(choices=CURRENCY_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))

    def __init__(self, *args, account=None, **kwargs):
        self.account = account
        super().__init__(*args, **kwargs)
        if account:
            self.fields['name'].initial = account.name
            self.fields['opening_balance'].initial = account.opening_balance
            self.fields['currency'].initial = account.currency

    def save(self):
        data = self.cleaned_data

        account = self.account or Account()
        account.name = data['name']
        account.opening_balance = data['opening_balance']
        account.currency = data['currency']
        account.save()
        return account