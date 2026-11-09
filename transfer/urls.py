from django.urls import path

from . import views

app_name = 'transfer'

urlpatterns = [
    path('', views.TransferListView.as_view(), name='transfer_list'),
    path('datatable/', views.TransferDatatableView.as_view(), name='transfer_datatable'),
    path('add/', views.TransferFormView.as_view(), name='transfer_add'),
    path('lots/', views.AvailableLotsView.as_view(), name='available_lots'),
    path('<int:pk>/', views.TransferDetailView.as_view(), name='transfer_detail'),
    path('<int:pk>/edit/', views.TransferFormView.as_view(), name='transfer_edit'),
    path('<int:pk>/confirm/', views.TransferConfirmView.as_view(), name='transfer_confirm'),
    path('<int:pk>/cancel/', views.TransferCancelView.as_view(), name='transfer_cancel'),
]
