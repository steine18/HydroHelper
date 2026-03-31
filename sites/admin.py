from django.contrib import admin
from .models import NovaPointLocator, Site, SiteRelationship


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display  = ('site_no', 'name', 'state', 'huc', 'latitude', 'longitude', 'transmit_interval_hours', 'transmit_offset_minutes')
    search_fields = ('site_no', 'name', 'state')
    ordering      = ('site_no',)


class NovaPointLocatorInline(admin.TabularInline):
    model  = NovaPointLocator
    extra  = 1
    fields = ('point_locator', 'parameter_type', 'label')


@admin.register(SiteRelationship)
class SiteRelationshipAdmin(admin.ModelAdmin):
    list_display  = ('upstream_site', 'downstream_site', 'offset_minutes', 'offset_type', 'label', 'created_by')
    list_filter   = ('offset_type', 'created_by')
    search_fields = ('upstream_site__site_no', 'downstream_site__site_no', 'label')
    autocomplete_fields = ('upstream_site', 'downstream_site')


@admin.register(NovaPointLocator)
class NovaPointLocatorAdmin(admin.ModelAdmin):
    list_display  = ('site', 'point_locator', 'parameter_type', 'label')
    list_filter   = ('parameter_type',)
    search_fields = ('site__site_no', 'point_locator', 'label')
