from django.conf import settings
from django.db import models

from .report_types import REPORT_TYPE_CHOICES, REPORT_TYPES_BY_ID


class StageQComparisonSite(models.Model):
    report = models.ForeignKey(
        'AnalysisReport',
        on_delete=models.CASCADE,
        related_name='stage_q_comparison_sites',
    )
    site = models.ForeignKey(
        'usgs_sites.Site',
        on_delete=models.CASCADE,
    )

    class Meta:
        ordering = ['site__site_no']
        unique_together = ('report', 'site')

    def __str__(self):
        return f"{self.report} — stage/Q comparison: {self.site.site_no}"


class PrecipComparisonSite(models.Model):
    report = models.ForeignKey(
        'AnalysisReport',
        on_delete=models.CASCADE,
        related_name='precip_comparison_sites',
    )
    site = models.ForeignKey(
        'usgs_sites.Site',
        on_delete=models.CASCADE,
    )

    class Meta:
        ordering = ['site__site_no']
        unique_together = ('report', 'site')

    def __str__(self):
        return f"{self.report} — comparison: {self.site.site_no}"


class PrecipCalibration(models.Model):
    report = models.ForeignKey(
        'AnalysisReport',
        on_delete=models.CASCADE,
        related_name='precip_calibrations',
    )
    date = models.DateField()
    desired_tips = models.FloatField()
    actual_tips = models.FloatField()

    class Meta:
        ordering = ['date']

    def error_pct(self):
        if self.desired_tips == 0:
            return None
        return (self.actual_tips - self.desired_tips) / self.desired_tips * 100


class AnalysisReport(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='analysis_reports',
    )
    site = models.ForeignKey(
        'usgs_sites.Site',
        on_delete=models.CASCADE,
        related_name='analysis_reports',
    )
    report_type = models.CharField(max_length=50, choices=REPORT_TYPE_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    section_data = models.JSONField(default=dict)
    prior_period_analysis = models.TextField(
        blank=True,
        help_text="Optional: paste the previous period's analysis text here to use as style reference in the Copilot prompt export.",
    )
    saved_to_reports = models.BooleanField(default=False)
    is_complete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        permissions = [('can_use_ai_assist', 'Can use AI assist')]
        unique_together = [('user', 'site', 'period_start', 'period_end')]

    def __str__(self):
        return (
            f"{self.site.site_no} — {self.get_report_type_display()} "
            f"({self.period_start} to {self.period_end})"
        )

    def completion_pct(self):
        rt = REPORT_TYPES_BY_ID.get(self.report_type)
        if not rt:
            return 0
        keys = [s['key'] for s in rt['sections']]
        if not keys:
            return 0
        filled = sum(1 for k in keys if self.section_data.get(k, '').strip())
        return round(filled / len(keys) * 100)
