from django.conf import settings
from django.db import models


class Site(models.Model):
    """
    Cached USGS monitoring site metadata.
    Records are auto-populated from the USGS site service API on first use
    via get_or_fetch(), so manual entry is not required.
    """
    site_no                 = models.CharField(max_length=20, unique=True)
    name                    = models.CharField(max_length=200)
    latitude                = models.FloatField(null=True, blank=True)
    longitude               = models.FloatField(null=True, blank=True)
    state                   = models.CharField(max_length=2, blank=True)
    huc                     = models.CharField(max_length=12, blank=True, verbose_name="HUC")
    transmit_interval_hours = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Scheduled ALERT2 transmit interval in hours (e.g. 1, 4, 8).",
    )
    transmit_offset_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text="Minutes offset within each interval (e.g. 10 means transmits at :10 past each interval start).",
    )

    class Meta:
        ordering = ['site_no']

    def __str__(self):
        return f"{self.site_no} — {self.name}"

    @classmethod
    def get_or_fetch(cls, site_no: str) -> "Site":
        """
        Return the Site for site_no from the database, fetching and caching
        metadata from the USGS site service API if not already present.
        """
        try:
            return cls.objects.get(site_no=site_no)
        except cls.DoesNotExist:
            pass

        from water_balance.usgs import USGSAPIError
        import requests

        try:
            response = requests.get(
                "https://waterservices.usgs.gov/nwis/site/",
                params={
                    "format": "rdb",
                    "sites": site_no,
                    "siteOutput": "basic",
                },
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise USGSAPIError(f"USGS site info request failed: {exc}") from exc

        # RDB basic output column indices (siteOutput=basic returns 12 columns):
        # 2=station_nm, 4=dec_lat_va, 5=dec_long_va, 11=huc_cd (no state field)
        site = cls(site_no=site_no)
        for line in response.text.splitlines():
            if line.startswith("#") or line.startswith("agency_cd") or line.startswith("5s"):
                continue
            parts = line.split("\t")
            if len(parts) >= 12 and parts[1] == site_no:
                site.name = parts[2]
                site.huc  = parts[11].strip()
                try:
                    site.latitude  = float(parts[4]) if parts[4].strip() else None
                    site.longitude = float(parts[5]) if parts[5].strip() else None
                except (ValueError, IndexError):
                    pass
                break

        site.save()
        return site


class SiteRelationship(models.Model):
    """
    A user-defined, reusable time-of-travel relationship between two USGS sites.
    Captures the known (or estimated) travel time from an upstream site to a
    downstream site. Designed to support flow-dependent offsets in the future.
    """

    class OffsetType(models.TextChoices):
        FIXED        = 'fixed',        'Fixed (minutes)'
        FLOW_DEPENDENT = 'flow_dependent', 'Flow-dependent (future)'

    created_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='site_relationships',
    )
    upstream_site   = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='downstream_relationships',
    )
    downstream_site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='upstream_relationships',
    )
    offset_minutes  = models.FloatField(
        default=0,
        help_text="Time-of-travel from upstream to downstream site (minutes).",
    )
    offset_type     = models.CharField(
        max_length=20,
        choices=OffsetType.choices,
        default=OffsetType.FIXED,
    )
    label           = models.CharField(max_length=100, blank=True)
    notes           = models.TextField(blank=True)

    class Meta:
        ordering = ['downstream_site__site_no', 'upstream_site__site_no']
        unique_together = ('created_by', 'upstream_site', 'downstream_site')

    def __str__(self):
        label = f" ({self.label})" if self.label else ""
        return (
            f"{self.upstream_site.site_no} → {self.downstream_site.site_no}"
            f" +{self.offset_minutes:.0f} min{label}"
        )


class LocatorGroup(models.Model):
    """
    A named group of Novastar point locators not associated with a USGS site.
    Useful for test channels, non-USGS sensors, or any collection of locators
    that should be displayed together in the ALERT2 dashboard.
    """
    name                    = models.CharField(max_length=200, unique=True)
    transmit_interval_hours = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Scheduled ALERT2 transmit interval in hours (e.g. 1, 4, 8).",
    )
    transmit_offset_minutes = models.PositiveSmallIntegerField(
        default=0,
        help_text="Minutes offset within each interval.",
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class NovaPointLocator(models.Model):
    """
    Maps a USGS site (or LocatorGroup) to a Novastar ALERT/ALERT2 point locator
    address. Exactly one of `site` or `group` must be set.
    """
    site            = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name='nova_point_locators',
        null=True, blank=True,
    )
    group           = models.ForeignKey(
        LocatorGroup,
        on_delete=models.CASCADE,
        related_name='nova_point_locators',
        null=True, blank=True,
    )
    point_locator   = models.CharField(
        max_length=50,
        help_text="ALERT or ALERT2 address from the Novastar Point Data Viewer.",
    )
    parameter_type  = models.CharField(
        max_length=100,
        help_text="Type of measurement (e.g. Stage, Precipitation, Discharge).",
    )
    label           = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['parameter_type']
        unique_together = [('site', 'point_locator'), ('group', 'point_locator')]

    def __str__(self):
        owner = self.site.site_no if self.site else (self.group.name if self.group else '—')
        label = f" — {self.label}" if self.label else ""
        return f"{owner} / {self.point_locator} ({self.parameter_type}){label}"
