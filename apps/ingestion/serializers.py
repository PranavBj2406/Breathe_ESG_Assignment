"""
DRF Serializers for Ingestion App.
"""

from rest_framework import serializers

from apps.ingestion.models import IngestionJob, IngestionSource, RawSAPRecord, RawUtilityRecord, RawTravelRecord


class IngestionSourceSerializer(serializers.ModelSerializer):
    """Serializer for configuring data sources."""

    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = IngestionSource
        fields = [
            "id", "tenant", "tenant_name", "name", "source_type",
            "api_endpoint", "api_username", "api_headers",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {
            "api_password_encrypted": {"write_only": True},
        }


class IngestionSourceCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating sources — excludes sensitive fields from response."""

    class Meta:
        model = IngestionSource
        fields = [
            "id", "tenant", "name", "source_type",
            "api_endpoint", "api_username", "api_password_encrypted",
            "api_headers", "is_active",
        ]


class IngestionJobSerializer(serializers.ModelSerializer):
    """Serializer for ingestion jobs."""

    source_name = serializers.CharField(source="source.name", read_only=True)
    source_type = serializers.CharField(source="source.source_type", read_only=True)
    triggered_by_username = serializers.CharField(source="triggered_by.username", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = IngestionJob
        fields = [
            "id", "tenant", "tenant_name", "source", "source_name", "source_type",
            "triggered_by", "triggered_by_username", "status",
            "raw_file", "original_filename", "file_size_bytes",
            "api_request_log", "records_fetched", "records_failed",
            "summary", "error_message", "started_at", "completed_at", "created_at",
        ]
        read_only_fields = [
            "status", "records_fetched", "records_failed", "summary",
            "error_message", "started_at", "completed_at", "created_at",
        ]


class IngestionJobDetailSerializer(serializers.ModelSerializer):
    """Detailed job view with nested raw record counts."""

    source_name = serializers.CharField(source="source.name", read_only=True)
    source_type = serializers.CharField(source="source.source_type", read_only=True)
    raw_sap_count = serializers.IntegerField(source="raw_sap_records.count", read_only=True)
    raw_utility_count = serializers.IntegerField(source="raw_utility_records.count", read_only=True)
    raw_travel_count = serializers.IntegerField(source="raw_travel_records.count", read_only=True)
    normalized_count = serializers.IntegerField(source="normalized_activities.count", read_only=True)

    class Meta:
        model = IngestionJob
        fields = [
            "id", "tenant", "source", "source_name", "source_type",
            "status", "raw_sap_count", "raw_utility_count", "raw_travel_count",
            "normalized_count", "summary", "error_message", "started_at",
            "completed_at", "created_at",
        ]


class SAPIngestRequestSerializer(serializers.Serializer):
    """Request body for triggering SAP ingestion."""
    source_id = serializers.UUIDField()
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=500)
    simulate = serializers.BooleanField(required=False, default=True)


class UtilityCSVUploadSerializer(serializers.Serializer):
    """Request body for utility CSV upload."""
    source_id = serializers.UUIDField()
    file = serializers.FileField()


class TravelIngestRequestSerializer(serializers.Serializer):
    """Request body for triggering travel ingestion."""
    source_id = serializers.UUIDField()
    date_from = serializers.DateField(required=False, allow_null=True)
    date_to = serializers.DateField(required=False, allow_null=True)
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=500)
    simulate = serializers.BooleanField(required=False, default=True)


class IngestionSummarySerializer(serializers.Serializer):
    """Response after ingestion completes."""
    job_id = serializers.UUIDField()
    status = serializers.CharField()
    total_records = serializers.IntegerField()
    success_count = serializers.IntegerField()
    flagged_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.CharField(), required=False)
    warnings = serializers.ListField(child=serializers.CharField(), required=False)


class RawSAPRecordSerializer(serializers.ModelSerializer):
    """Serializer for raw SAP records."""

    class Meta:
        model = RawSAPRecord
        fields = [
            "id", "purchase_order_id", "company_code", "plant", "material",
            "order_quantity", "order_unit", "net_price", "document_currency",
            "creation_date", "supplier", "checksum", "fetched_at",
        ]


class RawUtilityRecordSerializer(serializers.ModelSerializer):
    """Serializer for raw utility records."""

    class Meta:
        model = RawUtilityRecord
        fields = [
            "id", "account_number", "meter_id", "utility_type",
            "billing_period_start", "billing_period_end", "consumption",
            "consumption_unit", "total_cost", "cost_currency", "checksum", "fetched_at",
        ]


class RawTravelRecordSerializer(serializers.ModelSerializer):
    """Serializer for raw travel records."""

    class Meta:
        model = RawTravelRecord
        fields = [
            "id", "expense_report_id", "employee_id", "cost_center",
            "travel_type", "trip_date", "origin", "destination",
            "distance_km", "amount", "currency", "checksum", "fetched_at",
        ]