from django import forms
from django.contrib.auth import get_user_model

from .models import ATTACHMENT_EXTENSIONS, Category, Pad

User = get_user_model()


class CategoryForm(forms.Form):
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, category=None, **kwargs):
        self.category = category
        super().__init__(*args, **kwargs)
        if category:
            self.fields['name'].initial = category.name

    def save(self):
        data = self.cleaned_data

        category = self.category or Category()
        category.name = data['name']
        category.save()
        return category


class PadForm(forms.Form):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(), widget=forms.Select(attrs={'class': 'form-control'})
    )
    title = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    details = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'id': 'id_details'}))
    attachment = forms.FileField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    party_b_type = forms.ChoiceField(choices=Pad.PartyBType.choices, widget=forms.RadioSelect)
    party_b_employee = forms.ModelChoiceField(
        queryset=User.objects.filter(user_type='employee'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    party_b_name = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    party_b_email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, pad=None, **kwargs):
        self.pad = pad
        super().__init__(*args, **kwargs)
        if pad:
            self.fields['category'].initial = pad.category
            self.fields['title'].initial = pad.title
            self.fields['details'].initial = pad.details
            self.fields['party_b_type'].initial = pad.party_b_type
            self.fields['party_b_employee'].initial = pad.party_b_employee
            self.fields['party_b_name'].initial = pad.party_b_name
            self.fields['party_b_email'].initial = pad.party_b_email

    def clean_attachment(self):
        attachment = self.cleaned_data.get('attachment')
        if attachment:
            extension = attachment.name.rsplit('.', 1)[-1].lower()
            if extension not in ATTACHMENT_EXTENSIONS:
                raise forms.ValidationError('Unsupported file type.')
        return attachment

    def clean(self):
        cleaned_data = super().clean()
        party_b_type = cleaned_data.get('party_b_type')

        if party_b_type == Pad.PartyBType.EMPLOYEE:
            if not cleaned_data.get('party_b_employee'):
                self.add_error('party_b_employee', 'Please select an employee.')
        elif party_b_type == Pad.PartyBType.EXTERNAL:
            if not cleaned_data.get('party_b_name'):
                self.add_error('party_b_name', 'Please enter a name.')
            if not cleaned_data.get('party_b_email'):
                self.add_error('party_b_email', 'Please enter an email.')
        return cleaned_data

    def save(self, created_by=None):
        data = self.cleaned_data

        pad = self.pad or Pad(created_by=created_by)
        pad.category = data['category']
        pad.title = data['title']
        pad.details = data['details']
        pad.party_b_type = data['party_b_type']

        if data['party_b_type'] == Pad.PartyBType.EMPLOYEE:
            pad.party_b_employee = data['party_b_employee']
            pad.party_b_name = None
            pad.party_b_email = None
        else:
            pad.party_b_employee = None
            pad.party_b_name = data['party_b_name']
            pad.party_b_email = data['party_b_email']

        if data.get('attachment'):
            pad.attachment = data['attachment']

        pad.save()
        return pad


class SignatureForm(forms.Form):
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    confirm = forms.BooleanField(
        required=True,
        label='I confirm this is my digital signature and I agree to the contents of this document.',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )