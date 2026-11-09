from django.urls import path

from . import views

app_name = 'company'

urlpatterns = [
    path('', views.CompanyDetailView.as_view(), name='detail'),
    path('edit/', views.CompanyFormView.as_view(), name='form'),
]