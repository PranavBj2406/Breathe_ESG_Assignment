from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth.models import User
from apps.core.models import Tenant, LocationMapping


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def quick_setup(request):
    if request.method == "GET":
        tenant = Tenant.objects.first()
        if tenant:
            return Response({
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "setup_complete": User.objects.filter(username="admin").exists()
            })
        return Response({"message": "No tenant found"}, status=404)
    """One-time setup — creates admin user and seed data."""
    
    # Only run if no users exist
    if User.objects.filter(username="admin").exists():
        return Response({"message": "Setup already completed"}, status=200)
    
    # Create superuser
    User.objects.create_superuser(
        "admin", 
        "admin@breatheesg.com", 
        "BreatheESG2024!"
    )
    
    # Create tenant
    tenant, _ = Tenant.objects.get_or_create(
        slug="acme-corp",
        defaults={"name": "Acme Corporation"}
    )
    
    # Create location mappings
    mappings = [
        {
            "canonical_location_code": "LOC-BER-01",
            "canonical_name": "Berlin Manufacturing Plant",
            "sap_plant_code": "1200",
            "utility_account_number": "881-221-001",
            "travel_cost_center": "CC-BER-01",
        },
        {
            "canonical_location_code": "LOC-MUC-01",
            "canonical_name": "Munich Office",
            "sap_plant_code": "2000",
            "utility_account_number": "882-105-001",
            "travel_cost_center": "CC-MUC-02",
        },
        {
            "canonical_location_code": "LOC-FRA-01",
            "canonical_name": "Frankfurt Hub",
            "sap_plant_code": "1100",
            "travel_cost_center": "CC-FRA-03",
        },
    ]
    
    for m in mappings:
        LocationMapping.objects.get_or_create(
            tenant=tenant,
            canonical_location_code=m["canonical_location_code"],
            defaults=m,
        )
    
    return Response({
        "message": "Setup complete",
        "credentials": {
            "username": "admin",
            "password": "BreatheESG2024!"
        },
        "tenant": tenant.name,
        "locations_created": len(mappings),
    }, status=201)