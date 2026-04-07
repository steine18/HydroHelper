from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='alert2_index'),
    path('overview/', views.overview, name='alert2_overview'),
    path('group/<int:pk>/', views.group_data, name='alert2_group_data'),
    path('group/<int:pk>/summary/', views.group_summary, name='alert2_group_summary'),
    path('<str:site_no>/', views.site_data, name='alert2_site_data'),
    path('<str:site_no>/summary/', views.summary, name='alert2_summary'),
]
