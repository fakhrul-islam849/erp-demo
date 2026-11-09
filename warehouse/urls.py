from django.urls import path

from . import views

app_name = 'warehouse'

urlpatterns = [
    path('', views.WarehouseListView.as_view(), name='list'),
    path('datatable/', views.WarehouseDatatableView.as_view(), name='datatable'),
    path('add/', views.WarehouseFormView.as_view(), name='add'),
    path('<int:pk>/edit/', views.WarehouseFormView.as_view(), name='edit'),
    path('<int:pk>/delete/', views.WarehouseDeleteView.as_view(), name='delete'),
]
