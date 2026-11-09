from django import forms

from common.constants import COUNTRY_CHOICES
from common.validators import validate_phone_number

from .models import Supplier


class SupplierForm(forms.Form):
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    country = forms.ChoiceField(choices=COUNTRY_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))
    address = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))

    def __init__(self, *args, supplier=None, **kwargs):
        self.supplier = supplier
        super().__init__(*args, **kwargs)
        if supplier:
            self.fields['name'].initial = supplier.name
            self.fields['phone'].initial = supplier.phone
            self.fields['email'].initial = supplier.email
            self.fields['country'].initial = supplier.country
            self.fields['address'].initial = supplier.address

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        validate_phone_number(phone)
        return phone

    def save(self):
        data = self.cleaned_data

        supplier = self.supplier or Supplier()
        supplier.name = data['name']
        supplier.phone = data['phone']
        supplier.email = data['email']
        supplier.country = data['country']
        supplier.address = data['address']
        supplier.save()
        return supplier
