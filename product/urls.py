from django.urls import path

from . import views

app_name = 'product'

urlpatterns = [
    # Category
    path('category/', views.CategoryListView.as_view(), name='category_list'),
    path('category/datatable/', views.CategoryDatatableView.as_view(), name='category_datatable'),
    path('category/add/', views.CategoryFormView.as_view(), name='category_add'),
    path('category/<int:pk>/edit/', views.CategoryFormView.as_view(), name='category_edit'),
    path('category/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),

    # Sub-category
    path('subcategory/', views.SubCategoryListView.as_view(), name='subcategory_list'),
    path('subcategory/datatable/', views.SubCategoryDatatableView.as_view(), name='subcategory_datatable'),
    path('subcategory/add/', views.SubCategoryFormView.as_view(), name='subcategory_add'),
    path('subcategory/<int:pk>/edit/', views.SubCategoryFormView.as_view(), name='subcategory_edit'),
    path('subcategory/<int:pk>/delete/', views.SubCategoryDeleteView.as_view(), name='subcategory_delete'),

    # Product
    path('', views.ProductListView.as_view(), name='product_list'),
    path('datatable/', views.ProductDatatableView.as_view(), name='product_datatable'),
    path('search/', views.ProductSearchView.as_view(), name='product_search'),
    path('add/', views.ProductFormView.as_view(), name='product_add'),
    path('<int:pk>/edit/', views.ProductFormView.as_view(), name='product_edit'),
    path('<int:pk>/delete/', views.ProductDeleteView.as_view(), name='product_delete'),
]
