from django.urls import path

from . import views

urlpatterns = [
    path('', views.decode_view, name='alert2_parser_decode'),
    path('batch/', views.batch_view, name='alert2_parser_batch'),
]
