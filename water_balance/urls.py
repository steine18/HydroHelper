from django.urls import path
from . import views

urlpatterns = [
    path('', views.flow_balance_index, name='flow_balance_index'),
    path('config/<int:config_id>/load/', views.load_flow_balance, name='load_flow_balance'),
    path('config/<int:config_id>/delete/', views.delete_flow_balance, name='delete_flow_balance'),
    path('<str:site_number>/', views.flow_balance, name='flow_balance'),
    path('<str:site_number>/save/', views.save_flow_balance, name='save_flow_balance'),
]