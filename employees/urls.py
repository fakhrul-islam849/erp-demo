from django.urls import path

from . import views

app_name = 'employees'

urlpatterns = [
    path('', views.EmployeeListView.as_view(), name='list'),
    path('create/', views.EmployeeAccountCreateView.as_view(), name='create_account'),
    path('<uuid:uid>/info/', views.EmployeeInfoView.as_view(), name='info'),
    path('<uuid:uid>/credentials/', views.EmployeeCredentialsView.as_view(), name='credentials'),
    path('datatable/', views.EmployeeDatatableView.as_view(), name='datatable'),
    path('<uuid:uid>/', views.EmployeeDetailView.as_view(), name='detail'),
]

