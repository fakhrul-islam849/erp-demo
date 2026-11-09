from django import forms

from common.validators import validate_phone_number

from .models import Company


class CompanyForm(forms.Form):
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    address = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))
    contact_number = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    logo = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    company_number = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    trademark_number = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, company=None, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        if company:
            self.fields['name'].initial = company.name
            self.fields['address'].initial = company.address
            self.fields['contact_number'].initial = company.contact_number
            self.fields['email'].initial = company.email
            self.fields['company_number'].initial = company.company_number
            self.fields['trademark_number'].initial = company.trademark_number
        else:
            self.fields['logo'].required = True

    def clean_contact_number(self):
        contact_number = self.cleaned_data['contact_number']
        validate_phone_number(contact_number)
        return contact_number

    def save(self):
        data = self.cleaned_data

        company = self.company or Company()
        company.name = data['name']
        company.address = data['address']
        company.contact_number = data['contact_number']
        company.email = data['email']
        company.company_number = data['company_number']
        company.trademark_number = data['trademark_number']
        if data['logo']:
            company.logo = data['logo']
        company.save()
        return company