from datetime import date

from django import forms
from django.core.validators import FileExtensionValidator

from payment_account.models import Account

from .models import ATTACHMENT_EXTENSIONS, MAX_ATTACHMENT_MB, ExpenseCategory, validate_attachment_size


class CategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ['name']
        widgets = {'name': forms.TextInput(attrs={'class': 'form-control'})}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = ExpenseCategory.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('An expense category with this name already exists.')
        return name


class ExpenseForm(forms.Form):
    title = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    account = forms.ModelChoiceField(
        queryset=Account.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='The account the expense is paid from. It must have enough money.',
    )
    category = forms.ModelChoiceField(
        queryset=ExpenseCategory.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=0.01,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
    )
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    attachment = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=ATTACHMENT_EXTENSIONS), validate_attachment_size],
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': ','.join(f'.{ext}' for ext in ATTACHMENT_EXTENSIONS),
        }),
        help_text=f'Optional. PDF, JPG or PNG, up to {MAX_ATTACHMENT_MB} MB.',
    )
    clear_attachment = forms.BooleanField(required=False, label='Remove the current attachment')

    def __init__(self, *args, expense=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['attachment'].widget = forms.FileInput(attrs=self.fields['attachment'].widget.attrs)
        if expense:
            for name in ('title', 'account', 'category', 'amount', 'date'):
                self.fields[name].initial = getattr(expense, name)
            if not expense.attachment:
                del self.fields['clear_attachment']
        else:
            self.fields['date'].initial = date.today()
            del self.fields['clear_attachment']

    def clean_title(self):
        title = self.cleaned_data['title'].strip()
        if not title:
            raise forms.ValidationError('Enter a title.')
        return title

    def values(self):
        """The cleaned values in the shape save_expense() expects."""
        data = self.cleaned_data
        values = {name: data[name] for name in ('title', 'account', 'category', 'amount', 'date')}
        if data.get('attachment'):
            values['attachment'] = data['attachment']
        elif data.get('clear_attachment'):
            values['clear_attachment'] = True
        return values
