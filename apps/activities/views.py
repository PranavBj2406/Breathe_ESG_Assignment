"""
DRF Views for Activities App.
Analyst dashboard and review workflow endpoints.
"""

from decimal import Decimal
from django.db.models import Count, Sum
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activities.models import ActivityAuditLog, NormalizedActivity
from apps.activities.serializers import (
    ActivityAuditLogSerializer,
    ActivityStatusUpdateSerializer,
    DashboardSummarySerializer,
    NormalizedActivityDetailSerializer,
    NormalizedActivitySerializer,
)


class NormalizedActivityViewSet(viewsets.ModelViewSet):
    """
    ViewSet for analyst review of normalized activities.

    Endpoints:
    - GET /api/activities/ — list with filtering
    - GET /api/activities/{id}/ — detail with raw data and audit logs
    - POST /api/activities/{id}/approve/ — approve activity
    - POST /api/activities/{id}/flag/ — flag for attention
    - POST /api/activities/{id}/reject/ — reject activity
    - POST /api/activities/{id}/lock/ — lock for audit
    """
    serializer_class = NormalizedActivitySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["status", "scope_category", "activity_category", "source_type"]
    ordering_fields = ["activity_date", "created_at", "co2e_kg", "quantity"]
    ordering = ["-activity_date"]

    def get_queryset(self):
        """Filter by tenant and exclude soft-deleted."""
        # In production, filter by request.user's tenant
        return NormalizedActivity.objects.filter(
            is_deleted=False
        ).select_related(
            "canonical_location", "tenant", "created_by", "updated_by"
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return NormalizedActivityDetailSerializer
        return self.serializer_class

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Approve an activity."""
        activity = self.get_object()
        serializer = ActivityStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            activity.approve(
                user=request.user,
                notes=serializer.validated_data.get("notes"),
            )
            return Response({
                "id": activity.id,
                "status": activity.status,
                "message": "Activity approved successfully",
            })
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def flag(self, request, pk=None):
        """Flag an activity for attention."""
        activity = self.get_object()
        serializer = ActivityStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get("reason")
        if not reason:
            return Response(
                {"error": "Reason is required when flagging"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            activity.flag(
                user=request.user,
                reason=reason,
                notes=serializer.validated_data.get("notes"),
            )
            return Response({
                "id": activity.id,
                "status": activity.status,
                "flag_reason": activity.flag_reason,
                "message": "Activity flagged successfully",
            })
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Reject an activity."""
        activity = self.get_object()
        serializer = ActivityStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get("reason")
        if not reason:
            return Response(
                {"error": "Reason is required when rejecting"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            activity.reject(
                user=request.user,
                reason=reason,
            )
            return Response({
                "id": activity.id,
                "status": activity.status,
                "flag_reason": activity.flag_reason,
                "message": "Activity rejected successfully",
            })
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        """Lock an activity for external audit."""
        activity = self.get_object()

        try:
            activity.lock_for_audit(user=request.user)
            return Response({
                "id": activity.id,
                "status": activity.status,
                "message": "Activity locked for audit",
            })
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class DashboardSummaryView(generics.GenericAPIView):
    """
    GET /api/activities/dashboard/
    Returns summary statistics for the analyst dashboard.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # In production, filter by tenant
        queryset = NormalizedActivity.objects.filter(is_deleted=False)

        total = queryset.count()
        pending = queryset.filter(status="PENDING_REVIEW").count()
        flagged = queryset.filter(status="FLAGGED").count()
        approved = queryset.filter(status="APPROVED").count()
        rejected = queryset.filter(status="REJECTED").count()
        locked = queryset.filter(status="LOCKED_FOR_AUDIT").count()

        total_co2e = queryset.aggregate(
            total=Sum("co2e_kg")
        )["total"] or Decimal("0")

        # Round to 6 decimal places to match serializer
        total_co2e = total_co2e.quantize(Decimal("0.000001"))

        by_scope = dict(
            queryset.values("scope_category").annotate(
                count=Count("id"),
                co2e=Sum("co2e_kg"),
            ).values_list("scope_category", "count")
        )

        by_source = dict(
            queryset.values("source_type").annotate(
                count=Count("id"),
            ).values_list("source_type", "count")
        )

        data = {
            "total_activities": total,
            "pending_review": pending,
            "flagged": flagged,
            "approved": approved,
            "rejected": rejected,
            "locked_for_audit": locked,
            "total_co2e_kg": total_co2e,
            "by_scope": by_scope,
            "by_source": by_source,
        }

        serializer = DashboardSummarySerializer(data=data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data)


class ActivityAuditLogListView(generics.ListAPIView):
    """
    GET /api/activities/{activity_id}/logs/
    Returns audit logs for a specific activity.
    """
    serializer_class = ActivityAuditLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        activity_id = self.kwargs.get("activity_id")
        return ActivityAuditLog.objects.filter(
            activity_id=activity_id
        ).select_related("performed_by")