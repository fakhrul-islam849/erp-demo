"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.contrib.auth.decorators import login_required
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static

class HomeView(TemplateView):
    template_name = 'home.html'

home_view = login_required(HomeView.as_view())

urlpatterns = [
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),
    path('control-panel-x7k/', admin.site.urls),
    path('', include('django.contrib.auth.urls')),
    path('', home_view, name='home'),
    path('accounts/', include('accounts.urls')),
    path('employees/', include('employees.urls')),
    path('company/', include('company.urls')),
    path('warehouse/', include('warehouse.urls')),
    path('supplier/', include('supplier.urls')),
    path('product/', include('product.urls')),
    path('accounts-management/', include('payment_account.urls')),
    path('company-pad/', include('company_pad.urls')),
    path('purchase/', include('purchase.urls')),
    path('transfer/', include('transfer.urls')),
    path('sale/', include('sale.urls')),
    path('income/', include('income.urls')),
    path('expense/', include('expense.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
