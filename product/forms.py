from django import forms

from .models import Category, Product, SubCategory


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


class SubCategoryForm(forms.Form):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, subcategory=None, **kwargs):
        self.subcategory = subcategory
        super().__init__(*args, **kwargs)
        if subcategory:
            self.fields['category'].initial = subcategory.category_id
            self.fields['name'].initial = subcategory.name

    def save(self):
        data = self.cleaned_data

        subcategory = self.subcategory or SubCategory()
        subcategory.category = data['category']
        subcategory.name = data['name']
        subcategory.save()
        return subcategory


class ProductForm(forms.Form):
    subcategory = forms.ModelChoiceField(
        queryset=SubCategory.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    name = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
    details = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def __init__(self, *args, product=None, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)
        if product:
            self.fields['subcategory'].initial = product.subcategory_id
            self.fields['name'].initial = product.name
            self.fields['details'].initial = product.details

    def save(self):
        data = self.cleaned_data

        product = self.product or Product()
        product.subcategory = data['subcategory']
        product.name = data['name']
        product.details = data['details']
        product.save()
        return product
