from django.urls import path
from . import views

urlpatterns = [
    path('', views.flow_balance_index, name='flow_balance_index'),
    path('<str:site_number>/', views.flow_balance, name='flow_balance'),
]