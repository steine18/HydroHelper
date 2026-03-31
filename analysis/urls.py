from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='analysis_index'),
    path('new/', views.new_report, name='analysis_new'),
    path('<int:pk>/', views.report_detail, name='analysis_detail'),
    path('<int:pk>/autosave/', views.autosave, name='analysis_autosave'),
    path('<int:pk>/ai_assist/<str:section_key>/', views.ai_assist, name='analysis_ai_assist'),
    path('<int:pk>/ai_assist_all/', views.ai_assist_all, name='analysis_ai_assist_all'),
    path('<int:pk>/complete/', views.toggle_complete, name='analysis_toggle_complete'),
    path('<int:pk>/delete/', views.delete_report, name='analysis_delete_report'),
    path('<int:pk>/dates/', views.update_dates, name='analysis_update_dates'),
    path('<int:pk>/export_prompt/', views.export_prompt, name='analysis_export_prompt'),
    path('<int:pk>/export_prompt_copilot/', views.export_prompt_copilot, name='analysis_export_prompt_copilot'),
    path('<int:pk>/calibrations/add/', views.add_calibration, name='analysis_add_calibration'),
    path('<int:pk>/calibrations/<int:cal_pk>/delete/', views.delete_calibration, name='analysis_delete_calibration'),
    path('<int:pk>/comparison/add/', views.add_comparison_site, name='analysis_add_comparison_site'),
    path('<int:pk>/comparison/<int:comp_pk>/delete/', views.delete_comparison_site, name='analysis_delete_comparison_site'),
    path('<int:pk>/stage-q-comparison/add/', views.add_stage_q_comparison_site, name='analysis_add_stage_q_comparison'),
    path('<int:pk>/stage-q-comparison/<int:comp_pk>/delete/', views.delete_stage_q_comparison_site, name='analysis_delete_stage_q_comparison'),
]
