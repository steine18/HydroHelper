from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='alert2_index'),
    path('overview/', views.overview, name='alert2_overview'),
    path('<str:site_no>/', views.site_data, name='alert2_site_data'),
    path('<str:site_no>/summary/', views.summary, name='alert2_summary'),
]
