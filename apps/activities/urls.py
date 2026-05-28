"""
URL configuration for Activities App.
"""

from django.urls import path

from apps.activities.views import (
    ActivityAuditLogListView,
    DashboardSummaryView,
    NormalizedActivityViewSet,
)

urlpatterns = [
    # Activities
    path("", NormalizedActivityViewSet.as_view({"get": "list"}), name="activity-list"),
    path("<uuid:pk>/", NormalizedActivityViewSet.as_view({"get": "retrieve"}), name="activity-detail"),
    path("<uuid:pk>/approve/", NormalizedActivityViewSet.as_view({"post": "approve"}), name="activity-approve"),
    path("<uuid:pk>/flag/", NormalizedActivityViewSet.as_view({"post": "flag"}), name="activity-flag"),
    path("<uuid:pk>/reject/", NormalizedActivityViewSet.as_view({"post": "reject"}), name="activity-reject"),
    path("<uuid:pk>/lock/", NormalizedActivityViewSet.as_view({"post": "lock"}), name="activity-lock"),

    # Dashboard
    path("dashboard/", DashboardSummaryView.as_view(), name="dashboard-summary"),

    # Audit logs
    path("<uuid:activity_id>/logs/", ActivityAuditLogListView.as_view(), name="activity-logs"),
]