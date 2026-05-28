"""
DRF Views for Ingestion App.
Orchestrates data ingestion from SAP, utility CSV, and travel sources.
"""

from django.core.files.uploadedfile import UploadedFile
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import Tenant
from apps.ingestion.models import IngestionJob, IngestionSource, RawSAPRecord, RawUtilityRecord, RawTravelRecord
from apps.ingestion.serializers import (
    IngestionJobDetailSerializer,
    IngestionJobSerializer,
    IngestionSourceSerializer,
    IngestionSummarySerializer,
    SAPIngestRequestSerializer,
    TravelIngestRequestSerializer,
    UtilityCSVUploadSerializer,
)
from apps.ingestion.services.csv_parser import UtilityCSVParser
from apps.ingestion.services.normalizer import NormalizerService
from apps.ingestion.services.sap_client import SAPODataClient


class IngestionSourceViewSet(viewsets.ModelViewSet):
    """CRUD for ingestion sources."""
    serializer_class = IngestionSourceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # In a real app, filter by user's tenant
        return IngestionSource.objects.filter(is_active=True)


class IngestionJobViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only viewset for ingestion jobs with detail endpoint."""
    serializer_class = IngestionJobSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return IngestionJob.objects.all()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return IngestionJobDetailSerializer
        return self.serializer_class


class SAPIngestView(generics.GenericAPIView):
    """
    POST /api/ingestion/sap/
    Triggers SAP OData V4 data pull, saves raw records, normalizes.
    """
    serializer_class = SAPIngestRequestSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_id = serializer.validated_data["source_id"]
        source = get_object_or_404(IngestionSource, id=source_id, source_type="SAP_ODATA")

        # Create job
        job = IngestionJob.objects.create(
            tenant=source.tenant,
            source=source,
            triggered_by=request.user,
            status="RUNNING",
            api_request_log={
                "endpoint": source.api_endpoint,
                "date_from": str(serializer.validated_data.get("date_from")),
                "date_to": str(serializer.validated_data.get("date_to")),
                "limit": serializer.validated_data.get("limit", 50),
            },
        )

        try:
            # Fetch from SAP (simulated or real)
            client = SAPODataClient(
                {
                    "api_endpoint": source.api_endpoint,
                    "api_username": source.api_username,
                    "api_password": source.api_password_encrypted,
                },
                simulate=serializer.validated_data.get("simulate", True),
            )

            records = client.fetch_purchase_orders(
                limit=serializer.validated_data.get("limit", 50),
                date_from=serializer.validated_data.get("date_from"),
                date_to=serializer.validated_data.get("date_to"),
            )

            job.records_fetched = len(records)
            job.save()

            # Save raw records
            raw_records = []
            for r in records:
                raw = RawSAPRecord.objects.create(
                    ingestion_job=job,
                    tenant=source.tenant,
                    raw_payload=r,
                    purchase_order_id=r["PurchaseOrder"],
                    company_code=r["CompanyCode"],
                    plant=r["Plant"],
                    material=r["Material"],
                    material_description=r.get("MaterialDescription"),
                    order_quantity=r["OrderQuantity"],
                    order_unit=r["PurchaseOrderQuantityUnit"],
                    net_price=r.get("NetPriceAmount"),
                    document_currency=r.get("DocumentCurrency"),
                    creation_date=r["CreationDate"],
                    supplier=r.get("Supplier"),
                    supplier_name=r.get("SupplierName"),
                    checksum=SAPODataClient.compute_checksum(r),
                )
                raw_records.append(raw)

            # Normalize
            normalizer = NormalizerService(job, performed_by=request.user)
            stats = normalizer.normalize_sap_records(raw_records)

            # Update job status
            job.status = "SUCCESS" if stats["flagged"] == 0 else "REVIEW_REQUIRED"
            job.summary = {
                "total_rows": stats["total"],
                "normalized_rows": stats["success"],
                "flagged_rows": stats["flagged"],
                "failed_rows": stats["failed"],
            }
            job.save()

            return Response({
                "job_id": job.id,
                "status": job.status,
                "total_records": stats["total"],
                "success_count": stats["success"],
                "flagged_count": stats["flagged"],
                "failed_count": stats["failed"],
                "errors": stats["errors"],
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            job.status = "FAILED"
            job.error_message = str(e)
            job.save()
            return Response({
                "job_id": job.id,
                "status": "FAILED",
                "error": str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UtilityCSVUploadView(generics.GenericAPIView):
    """
    POST /api/ingestion/utility/
    Upload utility CSV, parse, save raw records, normalize.
    """
    serializer_class = UtilityCSVUploadSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_id = serializer.validated_data["source_id"]
        source = get_object_or_404(IngestionSource, id=source_id, source_type="UTILITY_CSV")
        file_obj = serializer.validated_data["file"]

        # Create job
        job = IngestionJob.objects.create(
            tenant=source.tenant,
            source=source,
            triggered_by=request.user,
            status="RUNNING",
            raw_file=file_obj,
            original_filename=file_obj.name,
            file_size_bytes=file_obj.size,
        )

        try:
            # Parse CSV
            parser = UtilityCSVParser(file_obj)
            records = parser.parse()
            warnings = parser.get_warnings()

            job.records_fetched = len(records)
            job.save()

            # Save raw records
            raw_records = []
            for r in records:
                raw = RawUtilityRecord.objects.create(
                    ingestion_job=job,
                    tenant=source.tenant,
                    raw_payload=r,
                    account_number=r["account_number"],
                    meter_id=r.get("meter_id"),
                    utility_type=r["utility_type"],
                    billing_period_start=r["billing_period_start"],
                    billing_period_end=r["billing_period_end"],
                    consumption=r["consumption"],
                    consumption_unit=r["consumption_unit"],
                    total_cost=r.get("total_cost"),
                    cost_currency=r.get("currency"),
                    tariff_code=r.get("tariff_code"),
                    checksum=r["_checksum"],
                )
                raw_records.append(raw)

            # Normalize
            normalizer = NormalizerService(job, performed_by=request.user)
            stats = normalizer.normalize_utility_records(raw_records)

            # Update job
            job.status = "SUCCESS" if stats["flagged"] == 0 else "REVIEW_REQUIRED"
            job.summary = {
                "total_rows": stats["total"],
                "normalized_rows": stats["success"],
                "flagged_rows": stats["flagged"],
                "failed_rows": stats["failed"],
            }
            job.save()

            return Response({
                "job_id": job.id,
                "status": job.status,
                "total_records": stats["total"],
                "success_count": stats["success"],
                "flagged_count": stats["flagged"],
                "failed_count": stats["failed"],
                "errors": stats["errors"],
                "warnings": warnings,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            job.status = "FAILED"
            job.error_message = str(e)
            job.save()
            return Response({
                "job_id": job.id,
                "status": "FAILED",
                "error": str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TravelIngestView(generics.GenericAPIView):
    """
    POST /api/ingestion/travel/
    Triggers travel data ingestion (simulated or real API).
    """
    serializer_class = TravelIngestRequestSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        source_id = serializer.validated_data["source_id"]
        source = get_object_or_404(IngestionSource, id=source_id, source_type="TRAVEL_API")

        job = IngestionJob.objects.create(
            tenant=source.tenant,
            source=source,
            triggered_by=request.user,
            status="RUNNING",
            api_request_log={
                "endpoint": source.api_endpoint,
                "date_from": str(serializer.validated_data.get("date_from")),
                "date_to": str(serializer.validated_data.get("date_to")),
                "limit": serializer.validated_data.get("limit", 50),
            },
        )

        try:
            # For prototype, simulate travel data
            # In production, would call actual travel API
            records = self._simulate_travel_data(serializer.validated_data.get("limit", 50))

            job.records_fetched = len(records)
            job.save()

            raw_records = []
            for r in records:
                raw = RawTravelRecord.objects.create(
                    ingestion_job=job,
                    tenant=source.tenant,
                    raw_payload=r,
                    expense_report_id=r["ExpenseReportID"],
                    employee_id=r.get("EmployeeID"),
                    cost_center=r.get("CostCenter"),
                    department_code=r.get("DepartmentCode"),
                    travel_type=r["TravelType"],
                    trip_date=r["TripDate"],
                    origin=r.get("Origin"),
                    destination=r.get("Destination"),
                    origin_airport_code=r.get("OriginAirportCode"),
                    destination_airport_code=r.get("DestinationAirportCode"),
                    distance_km=r.get("DistanceKm"),
                    amount=r["Amount"],
                    currency=r["Currency"],
                    booking_class=r.get("BookingClass"),
                    number_of_nights=r.get("NumberOfNights"),
                    checksum=SAPODataClient.compute_checksum(r),
                )
                raw_records.append(raw)

            # Normalize
            normalizer = NormalizerService(job, performed_by=request.user)
            stats = normalizer.normalize_travel_records(raw_records)

            job.status = "SUCCESS" if stats["flagged"] == 0 else "REVIEW_REQUIRED"
            job.summary = {
                "total_rows": stats["total"],
                "normalized_rows": stats["success"],
                "flagged_rows": stats["flagged"],
                "failed_rows": stats["failed"],
            }
            job.save()

            return Response({
                "job_id": job.id,
                "status": job.status,
                "total_records": stats["total"],
                "success_count": stats["success"],
                "flagged_count": stats["flagged"],
                "failed_count": stats["failed"],
                "errors": stats["errors"],
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            job.status = "FAILED"
            job.error_message = str(e)
            job.save()
            return Response({
                "job_id": job.id,
                "status": "FAILED",
                "error": str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _simulate_travel_data(self, limit: int) -> list[dict]:
        """Generate simulated travel data for prototype."""
        import random
        from datetime import datetime, timedelta

        travel_types = ["FLIGHT", "HOTEL", "GROUND", "RAIL"]
        airport_pairs = [
            ("BER", "LHR"), ("BER", "CDG"), ("BER", "JFK"),
            ("FRA", "LHR"), ("MUC", "LHR"), ("CDG", "JFK"),
        ]
        cost_centers = ["CC-BER-01", "CC-MUC-02", "CC-FRA-03"]

        records = []
        for i in range(limit):
            travel_type = random.choice(travel_types)
            trip_date = datetime.now() - timedelta(days=random.randint(1, 90))

            record = {
                "ExpenseReportID": f"EXP-2025-{random.randint(1000, 9999):04d}",
                "EmployeeID": f"E{random.randint(10000, 99999)}",
                "CostCenter": random.choice(cost_centers),
                "TravelType": travel_type,
                "TripDate": trip_date.strftime("%Y-%m-%d"),
                "Amount": str(round(random.uniform(50, 2000), 2)),
                "Currency": "EUR",
            }

            if travel_type == "FLIGHT":
                origin, dest = random.choice(airport_pairs)
                record["OriginAirportCode"] = origin
                record["DestinationAirportCode"] = dest
                record["DistanceKm"] = str(random.randint(200, 6500))
                record["BookingClass"] = random.choice(["ECONOMY", "BUSINESS", "FIRST"])
            elif travel_type == "HOTEL":
                record["NumberOfNights"] = random.randint(1, 7)
            elif travel_type == "GROUND":
                record["DistanceKm"] = str(random.randint(10, 500))
            elif travel_type == "RAIL":
                record["DistanceKm"] = str(random.randint(50, 800))

            records.append(record)

        return records