from django.urls import path

from . import views

app_name = 'supplier'

urlpatterns = [
    path('', views.SupplierListView.as_view(), name='list'),
    path('datatable/', views.SupplierDatatableView.as_view(), name='datatable'),
    path('add/', views.SupplierFormView.as_view(), name='add'),
    path('<int:pk>/edit/', views.SupplierFormView.as_view(), name='edit'),
    path('<int:pk>/delete/', views.SupplierDeleteView.as_view(), name='delete'),
]
