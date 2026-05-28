"""
Ingestion models: IngestionSource, IngestionJob, and all Raw*Record tables.
Uses Django default auth.User — no custom user model needed.
"""

import uuid

from django.db import models

from apps.core.models import Tenant


class IngestionSource(models.Model):
    """
    Pre-configured data source bound to a tenant.
    Analysts select from these, they do not type URLs.
    """
    SOURCE_TYPE_CHOICES = [
        ("SAP_ODATA", "SAP OData V4"),
        ("UTILITY_CSV", "Utility CSV Upload"),
        ("TRAVEL_API", "Travel API"),
        ("TRAVEL_CSV", "Travel CSV Upload"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="ingestion_sources",
    )
    name = models.CharField(max_length=255, help_text="Human-readable, e.g. 'SAP Production'")
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    is_active = models.BooleanField(default=True)

    # API sources (SAP, Travel API)
    api_endpoint = models.URLField(blank=True, null=True)
    api_username = models.CharField(max_length=255, blank=True, null=True)
    api_password_encrypted = models.CharField(max_length=500, blank=True, null=True)
    api_headers = models.JSONField(blank=True, null=True, help_text="Extra headers, e.g. x-csrf-token")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ingestion_sources"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.source_type})"


class IngestionJob(models.Model):
    """
    Single run of data ingestion. Immutable after completion.
    Tenant binding happens HERE, not in the raw payload.
    """
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("SUCCESS", "Success"),
        ("PARTIAL_SUCCESS", "Partial Success"),
        ("FAILED", "Failed"),
        ("REVIEW_REQUIRED", "Review Required"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="ingestion_jobs",
    )
    source = models.ForeignKey(
        IngestionSource,
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    triggered_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_jobs",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    # For file uploads
    raw_file = models.FileField(
        upload_to="uploads/%Y/%m/%d/",
        blank=True,
        null=True,
        help_text="Original uploaded file for audit",
    )
    original_filename = models.CharField(max_length=255, blank=True, null=True)
    file_size_bytes = models.PositiveIntegerField(blank=True, null=True)

    # For API pulls
    api_request_log = models.JSONField(
        blank=True,
        null=True,
        help_text="Query params, endpoint, timestamp for audit",
    )
    records_fetched = models.PositiveIntegerField(blank=True, null=True)
    records_failed = models.PositiveIntegerField(blank=True, null=True)

    # Summary for quick dashboard view
    summary = models.JSONField(
        blank=True,
        null=True,
        help_text="{total_rows: N, normalized_rows: M, flagged_rows: K}",
    )

    error_message = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ingestion_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status", "created_at"]),
            models.Index(fields=["source", "status"]),
        ]

    def __str__(self):
        return f"Job {self.id.hex[:8]} — {self.source.name} ({self.status})"


class RawSAPRecord(models.Model):
    """
    Exactly what came from SAP OData V4, plus extracted index fields.
    Never edited after creation. If normalization logic changes,
    reprocess from this table.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ingestion_job = models.ForeignKey(
        IngestionJob,
        on_delete=models.CASCADE,
        related_name="raw_sap_records",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="raw_sap_records",
    )

    # Exact payload for audit and reprocessing
    raw_payload = models.JSONField()

    # Extracted for indexing / querying (still raw, not normalized)
    purchase_order_id = models.CharField(max_length=20, db_index=True)
    company_code = models.CharField(max_length=4, db_index=True)
    purchasing_organization = models.CharField(max_length=10, blank=True, null=True)
    plant = models.CharField(max_length=4, db_index=True)
    material = models.CharField(max_length=40, db_index=True)
    material_description = models.CharField(max_length=255, blank=True, null=True)
    order_quantity = models.DecimalField(max_digits=20, decimal_places=3)
    order_unit = models.CharField(max_length=10)
    net_price = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    document_currency = models.CharField(max_length=3, blank=True, null=True)
    creation_date = models.DateField(db_index=True)
    supplier = models.CharField(max_length=20, blank=True, null=True)
    supplier_name = models.CharField(max_length=255, blank=True, null=True)

    # Audit / deduplication
    fetched_at = models.DateTimeField(auto_now_add=True)
    checksum = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 of raw_payload for deduplication",
    )

    class Meta:
        db_table = "raw_sap_records"
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["tenant", "company_code", "plant"]),
            models.Index(fields=["ingestion_job", "purchase_order_id"]),
            models.Index(fields=["tenant", "material", "creation_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ingestion_job", "purchase_order_id"],
                name="unique_po_per_job",
            ),
        ]

    def __str__(self):
        return f"SAP {self.purchase_order_id} — {self.material}"


class RawUtilityRecord(models.Model):
    """Exactly what came from utility CSV upload."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ingestion_job = models.ForeignKey(
        IngestionJob,
        on_delete=models.CASCADE,
        related_name="raw_utility_records",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="raw_utility_records",
    )

    raw_payload = models.JSONField()

    # Extracted raw fields
    account_number = models.CharField(max_length=50, db_index=True)
    meter_id = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    utility_type = models.CharField(
        max_length=20,
        choices=[
            ("ELECTRICITY", "Electricity"),
            ("NATURAL_GAS", "Natural Gas"),
            ("WATER", "Water"),
            ("STEAM", "Steam"),
            ("OTHER", "Other"),
        ],
    )
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    consumption = models.DecimalField(max_digits=20, decimal_places=3)
    consumption_unit = models.CharField(max_length=10)
    total_cost = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    cost_currency = models.CharField(max_length=3, blank=True, null=True)
    tariff_code = models.CharField(max_length=50, blank=True, null=True)

    fetched_at = models.DateTimeField(auto_now_add=True)
    checksum = models.CharField(max_length=64, db_index=True)

    class Meta:
        db_table = "raw_utility_records"
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["tenant", "account_number", "billing_period_start"]),
            models.Index(fields=["ingestion_job", "meter_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ingestion_job", "account_number", "meter_id", "billing_period_start"],
                name="unique_utility_reading_per_job",
            ),
        ]

    def __str__(self):
        return f"Utility {self.utility_type} — {self.account_number} ({self.billing_period_start})"


class RawTravelRecord(models.Model):
    """Exactly what came from travel API or CSV."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ingestion_job = models.ForeignKey(
        IngestionJob,
        on_delete=models.CASCADE,
        related_name="raw_travel_records",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="raw_travel_records",
    )

    raw_payload = models.JSONField()

    # Extracted raw fields
    expense_report_id = models.CharField(max_length=50, db_index=True)
    employee_id = models.CharField(max_length=50, blank=True, null=True)
    cost_center = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    department_code = models.CharField(max_length=20, blank=True, null=True)
    travel_type = models.CharField(
        max_length=20,
        choices=[
            ("FLIGHT", "Flight"),
            ("HOTEL", "Hotel"),
            ("GROUND", "Ground Transport"),
            ("RAIL", "Rail"),
            ("CAR_RENTAL", "Car Rental"),
        ],
    )
    trip_date = models.DateField(db_index=True)
    origin = models.CharField(max_length=100, blank=True, null=True)
    destination = models.CharField(max_length=100, blank=True, null=True)
    origin_airport_code = models.CharField(max_length=10, blank=True, null=True)
    destination_airport_code = models.CharField(max_length=10, blank=True, null=True)
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3)
    booking_class = models.CharField(max_length=20, blank=True, null=True)
    number_of_nights = models.PositiveIntegerField(blank=True, null=True)

    fetched_at = models.DateTimeField(auto_now_add=True)
    checksum = models.CharField(max_length=64, db_index=True)

    class Meta:
        db_table = "raw_travel_records"
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["tenant", "cost_center", "trip_date"]),
            models.Index(fields=["ingestion_job", "expense_report_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ingestion_job", "expense_report_id"],
                name="unique_expense_per_job",
            ),
        ]

    def __str__(self):
        return f"Travel {self.travel_type} — {self.expense_report_id}"