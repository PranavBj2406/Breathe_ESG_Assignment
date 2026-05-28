"""
Core models: Tenant and LocationMapping.
"""

import uuid

from django.db import models


class Tenant(models.Model):
    """Multi-tenancy root. Every record belongs to exactly one tenant."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "tenants"
        ordering = ["name"]

    def __str__(self):
        return self.name


class LocationMapping(models.Model):
    """
    Cross-source master data mapping.
    Aliases local codes from SAP, utility portals, and travel platforms
    to a single canonical location per tenant.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="location_mappings",
    )
    canonical_name = models.CharField(max_length=255)
    canonical_location_code = models.CharField(
        max_length=50,
        help_text="Internal stable identifier, e.g. LOC-BER-01",
    )

    # SAP aliases
    sap_plant_code = models.CharField(max_length=10, blank=True, null=True)
    sap_company_code = models.CharField(max_length=10, blank=True, null=True)
    sap_cost_center = models.CharField(max_length=20, blank=True, null=True)

    # Utility aliases
    utility_account_number = models.CharField(max_length=50, blank=True, null=True)
    utility_meter_id = models.CharField(max_length=50, blank=True, null=True)

    # Travel aliases
    travel_cost_center = models.CharField(max_length=20, blank=True, null=True)
    travel_department_code = models.CharField(max_length=20, blank=True, null=True)

    # Default categorization for this location
    default_scope = models.CharField(
        max_length=10,
        choices=[
            ("SCOPE_1", "Scope 1"),
            ("SCOPE_2", "Scope 2"),
            ("SCOPE_3", "Scope 3"),
        ],
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "location_mappings"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "canonical_location_code"],
                name="unique_canonical_location_per_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "sap_plant_code"]),
            models.Index(fields=["tenant", "utility_account_number"]),
            models.Index(fields=["tenant", "travel_cost_center"]),
        ]

    def __str__(self):
        return f"{self.canonical_name} ({self.tenant.name})"