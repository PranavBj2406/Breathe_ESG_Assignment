"""
DRF Serializers for Activities App.
"""

from rest_framework import serializers

from apps.activities.models import ActivityAuditLog, NormalizedActivity
from apps.core.models import LocationMapping


class NormalizedActivitySerializer(serializers.ModelSerializer):
    """Serializer for analyst-facing normalized activities."""

    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    location_name = serializers.CharField(source="canonical_location.canonical_name", read_only=True)
    location_code = serializers.CharField(source="canonical_location.canonical_location_code", read_only=True)
    ingestion_job_id = serializers.UUIDField(source="ingestion_job.id", read_only=True)
    raw_source_type = serializers.SerializerMethodField()
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    updated_by_username = serializers.CharField(source="updated_by.username", read_only=True)

    class Meta:
        model = NormalizedActivity
        fields = [
            "id", "tenant", "tenant_name", "source_type", "raw_source_type",
            "ingestion_job_id", "location_name", "location_code",
            "activity_date", "scope_category", "activity_category",
            "quantity", "quantity_unit", "emission_factor", "emission_factor_source",
            "co2e_kg", "spend_amount", "spend_currency",
            "status", "flag_reason", "analyst_notes",
            "version", "change_reason",
            "created_at", "updated_at",
            "created_by_username", "updated_by_username",
        ]
        read_only_fields = [
            "id", "tenant", "source_type", "ingestion_job", "raw_sap_record",
            "raw_utility_record", "raw_travel_record", "version",
            "created_at", "updated_at", "created_by", "updated_by",
        ]

    def get_raw_source_type(self, obj):
        """Return which raw record type this activity came from."""
        if obj.raw_sap_record:
            return "SAP"
        elif obj.raw_utility_record:
            return "Utility"
        elif obj.raw_travel_record:
            return "Travel"
        return "Unknown"


class NormalizedActivityDetailSerializer(serializers.ModelSerializer):
    """Detailed view with raw record nested data."""

    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    location_name = serializers.CharField(source="canonical_location.canonical_name", read_only=True)
    location_code = serializers.CharField(source="canonical_location.canonical_location_code", read_only=True)
    raw_data = serializers.SerializerMethodField()
    audit_logs = serializers.SerializerMethodField()

    class Meta:
        model = NormalizedActivity
        fields = [
            "id", "tenant", "tenant_name", "source_type",
            "location_name", "location_code",
            "activity_date", "scope_category", "activity_category",
            "quantity", "quantity_unit", "emission_factor", "emission_factor_source",
            "co2e_kg", "spend_amount", "spend_currency",
            "status", "flag_reason", "analyst_notes",
            "version", "change_reason", "previous_version",
            "created_at", "updated_at",
            "raw_data", "audit_logs",
        ]
        read_only_fields = fields

    def get_raw_data(self, obj):
        """Return the raw record payload."""
        if obj.raw_sap_record:
            return obj.raw_sap_record.raw_payload
        elif obj.raw_utility_record:
            return obj.raw_utility_record.raw_payload
        elif obj.raw_travel_record:
            return obj.raw_travel_record.raw_payload
        return None

    def get_audit_logs(self, obj):
        """Return recent audit logs for this activity."""
        logs = obj.audit_logs.order_by("-performed_at")[:5]
        return ActivityAuditLogSerializer(logs, many=True).data


class ActivityStatusUpdateSerializer(serializers.Serializer):
    """Serializer for status update requests."""
    status = serializers.ChoiceField(choices=[
        ("APPROVED", "Approved"),
        ("FLAGGED", "Flagged"),
        ("REJECTED", "Rejected"),
    ])
    reason = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ActivityAuditLogSerializer(serializers.ModelSerializer):
    """Serializer for audit log entries."""

    performed_by_username = serializers.CharField(source="performed_by.username", read_only=True)

    class Meta:
        model = ActivityAuditLog
        fields = [
            "id", "action", "performed_by_username", "performed_at",
            "snapshot", "reason",
        ]
        read_only_fields = fields


class DashboardSummarySerializer(serializers.Serializer):
    """Serializer for dashboard summary statistics."""
    total_activities = serializers.IntegerField()
    pending_review = serializers.IntegerField()
    flagged = serializers.IntegerField()
    approved = serializers.IntegerField()
    rejected = serializers.IntegerField()
    locked_for_audit = serializers.IntegerField()
    total_co2e_kg = serializers.DecimalField(max_digits=20, decimal_places=6)
    by_scope = serializers.DictField()
    by_source = serializers.DictField()