from django.urls import path

from . import views

app_name = 'purchase'

urlpatterns = [
    path('', views.PurchaseListView.as_view(), name='purchase_list'),
    path('datatable/', views.PurchaseDatatableView.as_view(), name='purchase_datatable'),
    path('add/', views.PurchaseFormView.as_view(), name='purchase_add'),
    path('suggest-price/', views.SuggestPriceView.as_view(), name='suggest_price'),
    path('<int:pk>/', views.PurchaseDetailView.as_view(), name='purchase_detail'),
    path('<int:pk>/edit/', views.PurchaseFormView.as_view(), name='purchase_edit'),
    path('<int:pk>/cancel/', views.PurchaseCancelView.as_view(), name='purchase_cancel'),
    path('adjustment-types/', views.AdjustmentTypeListView.as_view(), name='adjustment_type_list'),
    path('adjustment-types/datatable/', views.AdjustmentTypeDatatableView.as_view(), name='adjustment_type_datatable'),
    path('adjustment-types/add/', views.AdjustmentTypeFormView.as_view(), name='adjustment_type_add'),
    path('adjustment-types/<int:pk>/edit/', views.AdjustmentTypeFormView.as_view(), name='adjustment_type_edit'),
    path('adjustment-types/<int:pk>/delete/', views.AdjustmentTypeDeleteView.as_view(), name='adjustment_type_delete'),
]
