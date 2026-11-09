from django.urls import path

from . import views

app_name = 'sale'

urlpatterns = [
    path('', views.SaleListView.as_view(), name='sale_list'),
    path('datatable/', views.SaleDatatableView.as_view(), name='sale_datatable'),
    path('add/', views.SaleFormView.as_view(), name='sale_add'),
    path('lots/', views.AvailableLotsView.as_view(), name='available_lots'),
    path('<int:pk>/', views.SaleDetailView.as_view(), name='sale_detail'),
    path('<int:pk>/edit/', views.SaleFormView.as_view(), name='sale_edit'),
    path('<int:pk>/return/', views.SaleReturnView.as_view(), name='sale_return'),
    path('<int:pk>/damage/', views.SaleDamageView.as_view(), name='sale_damage'),
    path('<int:pk>/refund/', views.SaleRefundView.as_view(), name='sale_refund'),
    path('adjustment-types/', views.AdjustmentTypeListView.as_view(), name='adjustment_type_list'),
    path('adjustment-types/datatable/', views.AdjustmentTypeDatatableView.as_view(), name='adjustment_type_datatable'),
    path('adjustment-types/add/', views.AdjustmentTypeFormView.as_view(), name='adjustment_type_add'),
    path('adjustment-types/<int:pk>/edit/', views.AdjustmentTypeFormView.as_view(), name='adjustment_type_edit'),
    path('adjustment-types/<int:pk>/delete/', views.AdjustmentTypeDeleteView.as_view(), name='adjustment_type_delete'),
]
