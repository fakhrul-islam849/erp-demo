from django import forms

from .models import Warehouse


class WarehouseForm(forms.Form):
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    marketplace_name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    marketplace_location = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, warehouse=None, **kwargs):
        self.warehouse = warehouse
        super().__init__(*args, **kwargs)
        if warehouse:
            self.fields['name'].initial = warehouse.name
            self.fields['marketplace_name'].initial = warehouse.marketplace_name
            self.fields['marketplace_location'].initial = warehouse.marketplace_location

    def save(self):
        data = self.cleaned_data

        warehouse = self.warehouse or Warehouse()
        warehouse.name = data['name']
        warehouse.marketplace_name = data['marketplace_name']
        warehouse.marketplace_location = data['marketplace_location']
        warehouse.save()
        return warehouse