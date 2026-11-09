from django.urls import path

from . import views

app_name = 'income'

urlpatterns = [
    path('', views.IncomeListView.as_view(), name='income_list'),
    path('datatable/', views.IncomeDatatableView.as_view(), name='income_datatable'),
    path('add/', views.IncomeFormView.as_view(), name='income_add'),
    path('<int:pk>/edit/', views.IncomeFormView.as_view(), name='income_edit'),
    path('<int:pk>/delete/', views.IncomeDeleteView.as_view(), name='income_delete'),
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/datatable/', views.CategoryDatatableView.as_view(), name='category_datatable'),
    path('categories/add/', views.CategoryFormView.as_view(), name='category_add'),
    path('categories/<int:pk>/edit/', views.CategoryFormView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),
]
