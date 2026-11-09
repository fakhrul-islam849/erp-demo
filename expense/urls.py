from django.urls import path

from . import views

app_name = 'expense'

urlpatterns = [
    path('', views.ExpenseListView.as_view(), name='expense_list'),
    path('datatable/', views.ExpenseDatatableView.as_view(), name='expense_datatable'),
    path('add/', views.ExpenseFormView.as_view(), name='expense_add'),
    path('<int:pk>/edit/', views.ExpenseFormView.as_view(), name='expense_edit'),
    path('<int:pk>/delete/', views.ExpenseDeleteView.as_view(), name='expense_delete'),
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/datatable/', views.CategoryDatatableView.as_view(), name='category_datatable'),
    path('categories/add/', views.CategoryFormView.as_view(), name='category_add'),
    path('categories/<int:pk>/edit/', views.CategoryFormView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),
]
