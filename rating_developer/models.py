from django.conf import settings
from django.db import models


class RatingConfig(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rating_configs',
    )
    site = models.ForeignKey(
        'usgs_sites.Site',
        on_delete=models.CASCADE,
        related_name='rating_configs',
    )
    name = models.CharField(max_length=200)
    use_manual_rating = models.BooleanField(default=False)
    manual_rating_text = models.TextField(blank=True)
    hidden_measurement_nos = models.JSONField(default=list)
    cross_site_configs = models.JSONField(
        default=list,
        help_text='List of {site_no, offset_minutes, label} dicts for cross-site measurement transfer.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} — {self.site.site_no}"
