from django.urls import path

from . import views

app_name = 'payment_account'

urlpatterns = [
    path('', views.AccountListView.as_view(), name='list'),
    path('datatable/', views.AccountDatatableView.as_view(), name='datatable'),
    path('add/', views.AccountFormView.as_view(), name='add'),
    path('<int:pk>/edit/', views.AccountFormView.as_view(), name='edit'),
    path('<int:pk>/delete/', views.AccountDeleteView.as_view(), name='delete'),
]
