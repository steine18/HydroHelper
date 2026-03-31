from django.contrib import admin

from .models import AnalysisReport


@admin.register(AnalysisReport)
class AnalysisReportAdmin(admin.ModelAdmin):
    list_display = ['site', 'report_type', 'period_start', 'period_end', 'user', 'saved_to_reports', 'updated_at']
    list_filter = ['report_type', 'saved_to_reports']
    search_fields = ['site__site_no', 'user__username']
    raw_id_fields = ['user', 'site']
