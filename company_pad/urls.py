from django.urls import path

from . import views

app_name = 'company_pad'

urlpatterns = [
    # Category
    path('category/', views.CategoryListView.as_view(), name='category_list'),
    path('category/datatable/', views.CategoryDatatableView.as_view(), name='category_datatable'),
    path('category/add/', views.CategoryFormView.as_view(), name='category_add'),
    path('category/<int:pk>/edit/', views.CategoryFormView.as_view(), name='category_edit'),
    path('category/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),

    # Pad
    path('', views.PadListView.as_view(), name='pad_list'),
    path('datatable/', views.PadDatatableView.as_view(), name='pad_datatable'),
    path('add/', views.PadFormView.as_view(), name='pad_add'),
    path('<uuid:pk>/', views.PadDetailView.as_view(), name='pad_detail'),
    path('<uuid:pk>/edit/', views.PadFormView.as_view(), name='pad_edit'),
    path('<uuid:pk>/delete/', views.PadDeleteView.as_view(), name='pad_delete'),
    path('<uuid:pk>/release/', views.PadReleaseView.as_view(), name='pad_release'),
    path('<uuid:pk>/revert/', views.PadRevertToDraftView.as_view(), name='pad_revert_to_draft'),
    path('<uuid:pk>/sign-admin/', views.PadAdminSignView.as_view(), name='pad_sign_admin'),
    path('<uuid:pk>/sign-employee/', views.PadEmployeeSignView.as_view(), name='pad_sign_employee'),
    path('<uuid:pk>/share-link/generate/', views.PadGenerateShareLinkView.as_view(), name='pad_generate_share_link'),
    path('share/<str:token>/', views.PadPublicView.as_view(), name='pad_public'),
]