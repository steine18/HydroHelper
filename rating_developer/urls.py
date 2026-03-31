from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='rating_index'),
    path('new/', views.new_config, name='rating_new'),
    path('<int:pk>/', views.detail, name='rating_detail'),
    path('<int:pk>/update/', views.update_config, name='rating_update'),
    path('<int:pk>/toggle_measurement/', views.toggle_measurement, name='rating_toggle_measurement'),
]
