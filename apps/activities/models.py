"""
Activities models: NormalizedActivity (unified analyst-facing table) and ActivityAuditLog.
Uses Django default auth.User — no custom user model needed.
"""

import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import CheckConstraint, Q

from apps.core.models import LocationMapping, Tenant
from apps.ingestion.models import IngestionJob, RawSAPRecord, RawTravelRecord, RawUtilityRecord


class NormalizedActivity(models.Model):
    """
    The single table analysts review. Every row is a normalized emission activity.
    Source-agnostic. Links back to exactly one raw record.
    """
    SOURCE_TYPE_CHOICES = [
        ("SAP_PROCUREMENT", "SAP Procurement"),
        ("UTILITY_ELECTRICITY", "Utility Electricity"),
        ("UTILITY_GAS", "Utility Gas"),
        ("UTILITY_WATER", "Utility Water"),
        ("TRAVEL_FLIGHT", "Travel Flight"),
        ("TRAVEL_HOTEL", "Travel Hotel"),
        ("TRAVEL_GROUND", "Travel Ground"),
        ("TRAVEL_RAIL", "Travel Rail"),
    ]

    SCOPE_CHOICES = [
        ("SCOPE_1", "Scope 1"),
        ("SCOPE_2", "Scope 2"),
        ("SCOPE_3", "Scope 3"),
    ]

    ACTIVITY_CATEGORY_CHOICES = [
        ("STATIONARY_COMBUSTION", "Stationary Combustion"),
        ("MOBILE_COMBUSTION", "Mobile Combustion"),
        ("PURCHASED_ELECTRICITY", "Purchased Electricity"),
        ("PURCHASED_HEAT", "Purchased Heat / Steam"),
        ("PURCHASED_COOLING", "Purchased Cooling"),
        ("BUSINESS_TRAVEL_AIR", "Business Travel — Air"),
        ("BUSINESS_TRAVEL_HOTEL", "Business Travel — Hotel"),
        ("BUSINESS_TRAVEL_GROUND", "Business Travel — Ground"),
        ("BUSINESS_TRAVEL_RAIL", "Business Travel — Rail"),
        ("PURCHASED_GOODS", "Purchased Goods & Services"),
        ("WASTE", "Waste"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("PENDING_REVIEW", "Pending Review"),
        ("FLAGGED", "Flagged — Needs Attention"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("LOCKED_FOR_AUDIT", "Locked for Audit"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="normalized_activities",
    )

    # Source-of-truth tracking
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPE_CHOICES)
    ingestion_job = models.ForeignKey(
        IngestionJob,
        on_delete=models.PROTECT,
        related_name="normalized_activities",
    )

    # Polymorphic link back to raw record (exactly one must be non-null)
    raw_sap_record = models.ForeignKey(
        RawSAPRecord,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="normalized_activities",
    )
    raw_utility_record = models.ForeignKey(
        RawUtilityRecord,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="normalized_activities",
    )
    raw_travel_record = models.ForeignKey(
        RawTravelRecord,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="normalized_activities",
    )

    # Normalized dimensions
    canonical_location = models.ForeignKey(
        LocationMapping,
        on_delete=models.PROTECT,
        related_name="normalized_activities",
        blank=True,
        null=True,
        help_text="Null if location could not be mapped — analyst must resolve",
    )
    activity_date = models.DateField(db_index=True)
    scope_category = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    activity_category = models.CharField(max_length=30, choices=ACTIVITY_CATEGORY_CHOICES)

    # Normalized quantities (unified units)
    quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_unit = models.CharField(max_length=10)

    # Emission calculation
    emission_factor = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        blank=True,
        null=True,
        help_text="kg CO2e per quantity_unit",
    )
    emission_factor_source = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="e.g. DEFRA 2024, EPA GHG Emission Factors Hub",
    )
    co2e_kg = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0"))],
    )

    # Financial (primarily for procurement)
    spend_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        blank=True,
        null=True,
    )
    spend_currency = models.CharField(max_length=3, blank=True, null=True)

    # Review workflow
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING_REVIEW",
        db_index=True,
    )
    flag_reason = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Auto-populated by normalizer or analyst",
    )
    analyst_notes = models.TextField(blank=True, null=True)

    # Audit trail — uses Django default auth.User
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_activities",
    )
    updated_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_activities",
    )

    # Versioning for audit
    version = models.PositiveIntegerField(default=1)
    previous_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_versions",
        help_text="Points to the previous version if this row was edited",
    )
    change_reason = models.TextField(
        blank=True,
        null=True,
        help_text="Why was this row edited? Required for audit.",
    )

    # Soft delete for audit (never hard delete normalized rows)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    deleted_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_activities",
    )

    class Meta:
        db_table = "normalized_activities"
        ordering = ["-activity_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status", "activity_date"]),
            models.Index(fields=["tenant", "scope_category", "activity_category"]),
            models.Index(fields=["canonical_location", "activity_date"]),
            models.Index(fields=["tenant", "source_type", "status"]),
            models.Index(fields=["ingestion_job", "status"]),
        ]
        constraints = [
            # Ensure exactly one raw record FK is non-null
            CheckConstraint(
                check=(
                    Q(raw_sap_record__isnull=False, raw_utility_record__isnull=True, raw_travel_record__isnull=True)
                    | Q(raw_sap_record__isnull=True, raw_utility_record__isnull=False, raw_travel_record__isnull=True)
                    | Q(raw_sap_record__isnull=True, raw_utility_record__isnull=True, raw_travel_record__isnull=False)
                ),
                name="exactly_one_raw_source",
            ),
            # If status is LOCKED_FOR_AUDIT, co2e_kg must be present
            CheckConstraint(
                check=Q(status__in=["PENDING_REVIEW", "FLAGGED", "APPROVED", "REJECTED"]) | Q(co2e_kg__isnull=False),
                name="locked_requires_co2e",
            ),
        ]

    def __str__(self):
        return f"{self.source_type} — {self.quantity} {self.quantity_unit} ({self.status})"

    @transaction.atomic
    def approve(self, user, notes=None):
        """Approve this activity. Creates audit trail."""
        if self.status == "LOCKED_FOR_AUDIT":
            raise ValueError("Cannot modify locked record")

        old_status = self.status
        self.status = "APPROVED"
        self.analyst_notes = notes or self.analyst_notes
        self.updated_by = user
        self.save()

        ActivityAuditLog.objects.create(
            tenant=self.tenant,
            activity=self,
            action="APPROVED",
            performed_by=user,
            snapshot=self._snapshot(),
            reason=f"Approved from {old_status}. Notes: {notes}" if notes else f"Approved from {old_status}",
        )

    @transaction.atomic
    def flag(self, user, reason, notes=None):
        """Flag this activity for attention."""
        if self.status == "LOCKED_FOR_AUDIT":
            raise ValueError("Cannot modify locked record")

        old_status = self.status
        self.status = "FLAGGED"
        self.flag_reason = reason
        self.analyst_notes = notes or self.analyst_notes
        self.updated_by = user
        self.save()

        ActivityAuditLog.objects.create(
            tenant=self.tenant,
            activity=self,
            action="FLAGGED",
            performed_by=user,
            snapshot=self._snapshot(),
            reason=f"Flagged from {old_status}: {reason}",
        )

    @transaction.atomic
    def reject(self, user, reason):
        """Reject this activity."""
        if self.status == "LOCKED_FOR_AUDIT":
            raise ValueError("Cannot modify locked record")

        old_status = self.status
        self.status = "REJECTED"
        self.flag_reason = reason
        self.updated_by = user
        self.save()

        ActivityAuditLog.objects.create(
            tenant=self.tenant,
            activity=self,
            action="REJECTED",
            performed_by=user,
            snapshot=self._snapshot(),
            reason=f"Rejected from {old_status}: {reason}",
        )

    @transaction.atomic
    def lock_for_audit(self, user):
        """Lock this activity for audit. Irreversible without unlock."""
        if not self.co2e_kg:
            raise ValueError("Cannot lock record without CO2e calculation")

        self.status = "LOCKED_FOR_AUDIT"
        self.updated_by = user
        self.save()

        ActivityAuditLog.objects.create(
            tenant=self.tenant,
            activity=self,
            action="LOCKED",
            performed_by=user,
            snapshot=self._snapshot(),
            reason="Locked for external audit",
        )

    def _snapshot(self):
        """Serialize current state for audit log."""
        return {
            "id": str(self.id),
            "source_type": self.source_type,
            "scope_category": self.scope_category,
            "activity_category": self.activity_category,
            "quantity": str(self.quantity),
            "quantity_unit": self.quantity_unit,
            "co2e_kg": str(self.co2e_kg) if self.co2e_kg else None,
            "status": self.status,
            "flag_reason": self.flag_reason,
            "canonical_location": self.canonical_location.canonical_name if self.canonical_location else None,
        }


class ActivityAuditLog(models.Model):
    """
    Immutable log of every significant action on NormalizedActivity.
    Complements the versioning on NormalizedActivity itself.
    """
    ACTION_CHOICES = [
        ("CREATED", "Created"),
        ("UPDATED", "Updated"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("FLAGGED", "Flagged"),
        ("LOCKED", "Locked for Audit"),
        ("UNLOCKED", "Unlocked from Audit"),
        ("DELETED", "Soft Deleted"),
        ("RESTORED", "Restored"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    activity = models.ForeignKey(
        NormalizedActivity,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    performed_at = models.DateTimeField(auto_now_add=True)

    # Snapshot of the row at this point in time
    snapshot = models.JSONField(
        help_text="Full serialized state of the activity at the time of action",
    )
    reason = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "activity_audit_logs"
        ordering = ["-performed_at"]
        indexes = [
            models.Index(fields=["tenant", "activity", "-performed_at"]),
            models.Index(fields=["performed_by", "-performed_at"]),
        ]

    def __str__(self):
        return f"{self.action} on {self.activity.id.hex[:8]} by {self.performed_by}"