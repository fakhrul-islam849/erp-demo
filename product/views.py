from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from common.datatables import BaseDatatableView
from common.search import search_page
from common.utils import delete_or_protect

from .forms import CategoryForm, ProductForm, SubCategoryForm
from .models import Category, Product, SubCategory


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.user_type == 'admin'


# ---------- Category ----------

class CategoryListView(AdminRequiredMixin, TemplateView):
    template_name = 'product/category_list.html'


class CategoryDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {},  # Actions
    ]

    def get_queryset(self):
        return Category.objects.all()

    def render_row(self, obj):
        actions_html = render_to_string('product/category_row_actions.html', {'category': obj})
        return {'name': obj.name, 'actions': actions_html}


class CategoryFormView(AdminRequiredMixin, View):
    template_name = 'product/category_form.html'

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
            return redirect('product:category_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'category': category})


class CategoryDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        delete_or_protect(request, category, 'Category deleted successfully.')
        return redirect('product:category_list')


# ---------- Sub-category ----------

class SubCategoryListView(AdminRequiredMixin, TemplateView):
    template_name = 'product/subcategory_list.html'


class SubCategoryDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'search_fields': ['category__name'], 'order_field': 'category__name'},
        {},  # Actions
    ]

    def get_queryset(self):
        return SubCategory.objects.select_related('category').all()

    def render_row(self, obj):
        actions_html = render_to_string('product/subcategory_row_actions.html', {'subcategory': obj})
        return {'name': obj.name, 'category': obj.category.name, 'actions': actions_html}


class SubCategoryFormView(AdminRequiredMixin, View):
    template_name = 'product/subcategory_form.html'

    def get(self, request, pk=None):
        subcategory = get_object_or_404(SubCategory, pk=pk) if pk else None
        form = SubCategoryForm(subcategory=subcategory)
        return render(request, self.template_name, {'form': form, 'subcategory': subcategory})

    def post(self, request, pk=None):
        subcategory = get_object_or_404(SubCategory, pk=pk) if pk else None
        is_new = subcategory is None
        form = SubCategoryForm(request.POST, subcategory=subcategory)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sub-category added successfully.' if is_new else 'Sub-category updated successfully.')
            return redirect('product:subcategory_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'subcategory': subcategory})


class SubCategoryDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        subcategory = get_object_or_404(SubCategory, pk=pk)
        delete_or_protect(request, subcategory, 'Sub-category deleted successfully.')
        return redirect('product:subcategory_list')


# ---------- Product ----------

class ProductListView(AdminRequiredMixin, TemplateView):
    template_name = 'product/product_list.html'


class ProductDatatableView(AdminRequiredMixin, BaseDatatableView):
    default_order_field = '-created_at'
    columns = [
        {'search_fields': ['name'], 'order_field': 'name'},
        {'search_fields': ['subcategory__name'], 'order_field': 'subcategory__name'},
        {},  # Actions
    ]

    def get_queryset(self):
        return Product.objects.select_related('subcategory').all()

    def render_row(self, obj):
        actions_html = render_to_string('product/product_row_actions.html', {'product': obj})
        return {'name': obj.name, 'subcategory': obj.subcategory.name, 'actions': actions_html}


class ProductFormView(AdminRequiredMixin, View):
    template_name = 'product/product_form.html'

    def get(self, request, pk=None):
        product = get_object_or_404(Product, pk=pk) if pk else None
        form = ProductForm(product=product)
        return render(request, self.template_name, {'form': form, 'product': product})

    def post(self, request, pk=None):
        product = get_object_or_404(Product, pk=pk) if pk else None
        is_new = product is None
        form = ProductForm(request.POST, product=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product added successfully.' if is_new else 'Product updated successfully.')
            return redirect('product:product_list')
        messages.error(request, 'Please fix the errors below.')
        return render(request, self.template_name, {'form': form, 'product': product})


class ProductDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        delete_or_protect(request, product, 'Product deleted successfully.')
        return redirect('product:product_list')


class ProductSearchView(AdminRequiredMixin, View):
    """Products for a search-as-you-type dropdown (ten random ones until you type)."""

    def get(self, request):
        products, more = search_page(
            Product.objects.all(), request.GET.get('q'), request.GET.get('page'), 'name', ('name', 'id'),
        )
        products.sort(key=lambda product: (product.name.lower(), product.pk))
        return JsonResponse({
            'products': [{'id': product.pk, 'name': product.name} for product in products],
            'more': more,
        })
