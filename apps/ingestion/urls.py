"""
URL configuration for Ingestion App.
"""

from django.urls import path

from apps.ingestion.views import (
    IngestionJobViewSet,
    IngestionSourceViewSet,
    SAPIngestView,
    TravelIngestView,
    UtilityCSVUploadView,
)

urlpatterns = [
    # Sources
    path("sources/", IngestionSourceViewSet.as_view({"get": "list", "post": "create"}), name="source-list"),
    path("sources/<uuid:pk>/", IngestionSourceViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}), name="source-detail"),

    # Jobs
    path("jobs/", IngestionJobViewSet.as_view({"get": "list"}), name="job-list"),
    path("jobs/<uuid:pk>/", IngestionJobViewSet.as_view({"get": "retrieve"}), name="job-detail"),

    # Ingestion endpoints
    path("sap/", SAPIngestView.as_view(), name="sap-ingest"),
    path("utility/", UtilityCSVUploadView.as_view(), name="utility-upload"),
    path("travel/", TravelIngestView.as_view(), name="travel-ingest"),
]