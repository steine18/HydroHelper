from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='rating_index'),
    path('new/', views.new_config, name='rating_new'),
    path('<int:pk>/', views.detail, name='rating_detail'),
    path('<int:pk>/update/', views.update_config, name='rating_update'),
    path('<int:pk>/toggle_measurement/', views.toggle_measurement, name='rating_toggle_measurement'),
    path('<int:pk>/cross-site/add/', views.add_cross_site, name='rating_add_cross_site'),
    path('<int:pk>/cross-site/remove/', views.remove_cross_site, name='rating_remove_cross_site'),
    path('<int:pk>/cross-site/update/', views.update_cross_site, name='rating_update_cross_site'),
]
