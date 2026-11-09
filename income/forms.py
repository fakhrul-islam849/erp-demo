from datetime import date

from django import forms

from payment_account.models import Account

from .models import Income, IncomeCategory


class CategoryForm(forms.ModelForm):
    class Meta:
        model = IncomeCategory
        fields = ['name']
        widgets = {'name': forms.TextInput(attrs={'class': 'form-control'})}

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        duplicates = IncomeCategory.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError('An income category with this name already exists.')
        return name


class IncomeForm(forms.Form):
    title = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    account = forms.ModelChoiceField(
        queryset=Account.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='The account that receives the money.',
    )
    category = forms.ModelChoiceField(
        queryset=IncomeCategory.objects.order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=0.01,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01'}),
    )
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))

    def __init__(self, *args, income=None, **kwargs):
        super().__init__(*args, **kwargs)
        if income:
            for name in self.fields:
                self.fields[name].initial = getattr(income, name)
        else:
            self.fields['date'].initial = date.today()

    def clean_title(self):
        title = self.cleaned_data['title'].strip()
        if not title:
            raise forms.ValidationError('Enter a title.')
        return title

    def values(self):
        """The cleaned values in the shape save_income() expects."""
        return {name: self.cleaned_data[name] for name in self.fields}
