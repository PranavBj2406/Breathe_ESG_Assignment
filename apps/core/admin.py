# apps/core/admin.py
from django.contrib import admin
from apps.core.models import Tenant, LocationMapping

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "created_at"]

@admin.register(LocationMapping)
class LocationMappingAdmin(admin.ModelAdmin):
    list_display = ["tenant", "canonical_name", "canonical_location_code", "is_active"]
    list_filter = ["tenant", "is_active"]