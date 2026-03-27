from django.conf import settings
from django.db import models


class FlowBalanceConfig(models.Model):
    """
    A saved Flow Balance plot configuration belonging to a user.
    Stores the primary site, date range, error band settings, and the full
    list of comparison site configurations so the plot can be exactly restored.
    """
    user            = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='flow_balance_configs',
    )
    primary_site    = models.ForeignKey(
        'sites.Site',
        on_delete=models.CASCADE,
        related_name='flow_balance_configs',
    )
    name            = models.CharField(max_length=100)
    start_date      = models.DateField(null=True, blank=True)
    end_date        = models.DateField(null=True, blank=True)
    show_band       = models.BooleanField(default=True)
    error_pct       = models.FloatField(default=10)
    # List of dicts: {site_no, offset_minutes, discharge_offset,
    #                 offset_type, operation, group}
    comparison_sites = models.JSONField(default=list)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('user', 'name')

    def __str__(self):
        return f"{self.name} ({self.primary_site.site_no})"

    def to_querystring(self):
        """Return a dict of GET params that restores this configuration."""
        params = {
            'start': self.start_date.isoformat() if self.start_date else '',
            'end':   self.end_date.isoformat()   if self.end_date   else '',
            'show_band':       '1' if self.show_band else '',
            'error_pct':       str(self.error_pct),
            'band_submitted':  '1',
            'compare_site':    [c['site_no']           for c in self.comparison_sites],
            'compare_offset':  [str(c['offset_minutes'])  for c in self.comparison_sites],
            'compare_discharge_offset': [str(c['discharge_offset']) for c in self.comparison_sites],
            'compare_offset_type':      [c['offset_type']           for c in self.comparison_sites],
            'compare_operation':        [c['operation']             for c in self.comparison_sites],
            'compare_group':            [c['group']                 for c in self.comparison_sites],
        }
        return params
