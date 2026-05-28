"""
SAP OData V4 Client — Simulated for prototype, structured for real deployment.

Researches:
- SAP S/4HANA OData V4 service: API_PURCHASEORDER_PROCESS_SRV
- Entity: PurchaseOrder (root), PurchaseOrderItem (line items)
- Real fields: PurchaseOrder, CompanyCode, PurchasingOrganization, Plant,
  Material, OrderQuantity, PurchaseOrderQuantityUnit, NetPriceAmount,
  DocumentCurrency, CreationDate, Supplier

What we simulate:
- Realistic field names and data types (quantities as strings with 3 decimals)
- German plant codes, ISO currency codes
- Inconsistent units (KG, L, M3, TON, PC)
- Missing descriptions (some materials have no text)
- CompanyCode that means nothing without tenant context

What would break in real deployment:
- Custom append structures in SAP (Z-fields)
- OData pagination ($skip/$top) not handled here
- CSRF token fetching for state-changing operations
- OAuth2 token refresh logic
- SAP instances with different languages (DESCR in German)
- Rate limiting on SAP gateway
"""

import hashlib
import json
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import requests
from django.conf import settings


class SAPODataClient:
    """
    Client for SAP OData V4 Purchase Order API.

    In prototype mode (default), returns fabricated data that mirrors
    real OData response structure. In production mode, would hit
    actual SAP S/4HANA instance.
    """

    # Realistic SAP material codes and their typical units
    MATERIAL_MASTER = {
        "RAW-STEEL-001": {"desc": "Raw Steel Sheet", "typical_unit": "KG", "scope": "SCOPE_3", "category": "PURCHASED_GOODS"},
        "RAW-STEEL-002": {"desc": "Steel Coil Hot Rolled", "typical_unit": "TON", "scope": "SCOPE_3", "category": "PURCHASED_GOODS"},
        "FUEL-DIESEL-01": {"desc": "Diesel Fuel", "typical_unit": "L", "scope": "SCOPE_1", "category": "MOBILE_COMBUSTION"},
        "FUEL-NGAS-001": {"desc": "Natural Gas", "typical_unit": "M3", "scope": "SCOPE_1", "category": "STATIONARY_COMBUSTION"},
        "ELEC-COMP-001": {"desc": "Electrical Components", "typical_unit": "PC", "scope": "SCOPE_3", "category": "PURCHASED_GOODS"},
        "PKG-CARDB-01": {"desc": "Cardboard Packaging", "typical_unit": "KG", "scope": "SCOPE_3", "category": "PURCHASED_GOODS"},
        "CHEM-SOLV-01": {"desc": "Industrial Solvent", "typical_unit": "L", "scope": "SCOPE_3", "category": "PURCHASED_GOODS"},
        "OFFICE-PPR-01": {"desc": "Office Paper A4", "typical_unit": "PC", "scope": "SCOPE_3", "category": "PURCHASED_GOODS"},
    }

    SAP_PLANTS = ["1000", "1100", "1200", "1300", "2000"]
    COMPANY_CODES = ["1000", "2000"]
    PURCH_ORGS = ["1710", "1720", "1730"]
    SUPPLIERS = [
        {"code": "S0001", "name": "ThyssenKrupp Materials"},
        {"code": "S0002", "name": "BASF SE"},
        {"code": "S0003", "name": "Shell Energy"},
        {"code": "S0004", "name": "Siemens AG"},
        {"code": "S0005", "name": "Mondi Packaging"},
        {"code": "S0006", "name": "Local Fuel Supplier GmbH"},
    ]

    def __init__(self, source_config: dict, simulate: bool = True):
        """
        Args:
            source_config: Dict with api_endpoint, api_username, api_password
            simulate: If True, return fabricated data. If False, hit real SAP.
        """
        self.source_config = source_config
        self.simulate = simulate
        self.base_url = source_config.get("api_endpoint", "")
        self.session = requests.Session()
        if not simulate:
            self.session.auth = (
                source_config.get("api_username", ""),
                source_config.get("api_password", ""),
            )
            self.session.headers.update({
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-csrf-token": "fetch",  # Real SAP requires CSRF for POST
            })

    def fetch_purchase_orders(self, limit: int = 50, date_from: str = None, date_to: str = None) -> list[dict]:
        """
        Fetch purchase orders. In simulation, generates realistic data.
        In production, would call:
        GET /sap/opu/odata4/sap/api_purchaseorder_process_srv/0001/PurchaseOrder
        """
        if self.simulate:
            return self._simulate_purchase_orders(limit, date_from, date_to)

        # Real OData V4 call structure
        url = f"{self.base_url}/PurchaseOrder"
        params = {
            "$top": limit,
            "$select": "PurchaseOrder,CompanyCode,PurchasingOrganization,Plant,Material,OrderQuantity,PurchaseOrderQuantityUnit,NetPriceAmount,DocumentCurrency,CreationDate,Supplier",
            "$expand": "to_PurchaseOrderItem",
        }
        if date_from:
            params["$filter"] = f"CreationDate ge {date_from}"
        if date_to:
            filter_clause = params.get("$filter", "")
            params["$filter"] = f"{filter_clause} and CreationDate le {date_to}" if filter_clause else f"CreationDate le {date_to}"

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json().get("value", [])
        except requests.exceptions.Timeout:
            raise SAPConnectionError("SAP OData request timed out after 30s")
        except requests.exceptions.HTTPError as e:
            raise SAPConnectionError(f"SAP returned HTTP {e.response.status_code}: {e.response.text}")
        except requests.exceptions.ConnectionError:
            raise SAPConnectionError(f"Could not connect to SAP at {self.base_url}")

    def _simulate_purchase_orders(self, limit: int, date_from: str = None, date_to: str = None) -> list[dict]:
        """Generate fabricated but structurally realistic SAP data."""
        records = []

        # Default date range: last 90 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        if date_from:
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        if date_to:
            end_date = datetime.strptime(date_to, "%Y-%m-%d")

        for i in range(limit):
            material_code = random.choice(list(self.MATERIAL_MASTER.keys()))
            material_info = self.MATERIAL_MASTER[material_code]
            supplier = random.choice(self.SUPPLIERS)
            plant = random.choice(self.SAP_PLANTS)
            company_code = random.choice(self.COMPANY_CODES)

            # Realistic quantity based on unit
            unit = material_info["typical_unit"]
            if unit == "KG":
                qty = Decimal(str(random.uniform(100, 5000))).quantize(Decimal("0.001"))
            elif unit == "TON":
                qty = Decimal(str(random.uniform(1, 50))).quantize(Decimal("0.001"))
            elif unit == "L":
                qty = Decimal(str(random.uniform(50, 10000))).quantize(Decimal("0.001"))
            elif unit == "M3":
                qty = Decimal(str(random.uniform(100, 5000))).quantize(Decimal("0.001"))
            else:  # PC
                qty = Decimal(str(random.randint(10, 5000)))

            # Net price: roughly €0.5-€50 per unit depending on material
            price_per_unit = random.uniform(0.5, 50.0)
            net_price = (qty * Decimal(str(price_per_unit))).quantize(Decimal("0.01"))

            # Random date within range
            days_offset = random.randint(0, (end_date - start_date).days)
            creation_date = start_date + timedelta(days=days_offset)

            # 10% chance of missing description (realistic SAP behavior)
            material_desc = material_info["desc"] if random.random() > 0.1 else None

            record = {
                "PurchaseOrder": f"450000{random.randint(1000, 9999):04d}",
                "CompanyCode": company_code,
                "PurchasingOrganization": random.choice(self.PURCH_ORGS),
                "Plant": plant,
                "Material": material_code,
                "MaterialDescription": material_desc,
                "OrderQuantity": str(qty),  # SAP returns quantities as strings
                "PurchaseOrderQuantityUnit": unit,
                "NetPriceAmount": str(net_price),
                "DocumentCurrency": "EUR",  # Could be USD, GBP in multi-currency
                "CreationDate": creation_date.strftime("%Y-%m-%d"),
                "Supplier": supplier["code"],
                "SupplierName": supplier["name"],
                # Metadata not in real payload but useful for simulation context
                "_simulated_scope": material_info["scope"],
                "_simulated_category": material_info["category"],
            }
            records.append(record)

        return records

    @staticmethod
    def compute_checksum(record: dict) -> str:
        """SHA-256 of canonical JSON for deduplication."""
        canonical = json.dumps(record, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SAPConnectionError(Exception):
    """Custom exception for SAP connectivity issues."""
    pass