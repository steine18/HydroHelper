from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='approval_index'),
    path('new/', views.new_approval, name='approval_new'),
    path('<int:pk>/', views.approval_detail, name='approval_detail'),
    path('<int:pk>/autosave/', views.autosave, name='approval_autosave'),
    path('<int:pk>/complete/', views.toggle_complete, name='approval_toggle_complete'),
    path('<int:pk>/delete/', views.delete_approval, name='approval_delete'),
    path('<int:pk>/dates/', views.update_dates, name='approval_update_dates'),
    path('<int:pk>/report/', views.approval_report, name='approval_report'),
    path('<int:pk>/export-docx/', views.export_docx, name='approval_export_docx'),
]
