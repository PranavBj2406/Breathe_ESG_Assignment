"""
Normalizer Service v4 — Fixed emission factors and complete material coverage.
"""

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.activities.models import ActivityAuditLog, NormalizedActivity
from apps.core.models import LocationMapping
from apps.ingestion.models import IngestionJob


class NormalizerError(Exception):
    pass


class NormalizerService:
    # EMISSION_FACTORS: kg CO2e per normalized unit
    EMISSION_FACTORS = {
        # Fuels (Scope 1)
        ("FUEL-DIESEL-01", "L"): Decimal("2.68"),
        ("FUEL-DIESEL-01", "KG"): Decimal("3.15"),  # diesel density ~0.85 kg/L
        ("FUEL-NGAS-001", "M3"): Decimal("2.02"),
        ("FUEL-NGAS-001", "L"): Decimal("0.00202"),  # 1 m3 = 1000 L

        # Electricity (Scope 2)
        ("ELECTRICITY", "KWH"): Decimal("0.233"),
        ("ELECTRICITY", "MWH"): Decimal("233.0"),

        # Travel (Scope 3)
        ("FLIGHT_SHORT_HAUL", "KM"): Decimal("0.255"),
        ("FLIGHT_LONG_HAUL", "KM"): Decimal("0.195"),
        ("HOTEL", "NIGHT"): Decimal("10.4"),
        ("GROUND_CAR", "KM"): Decimal("0.192"),
        ("GROUND_RAIL", "KM"): Decimal("0.041"),

        # Purchased goods (Scope 3) — by normalized unit
        ("PURCHASED_GOODS", "KG"): Decimal("1.5"),
        ("PURCHASED_GOODS", "TON"): Decimal("1500.0"),
        ("PURCHASED_GOODS", "PC"): Decimal("2.0"),
        ("PURCHASED_GOODS", "L"): Decimal("0.5"),  # generic liquid goods
    }

    # ALL materials must be in this map
    MATERIAL_CLASSIFICATION = {
        "FUEL-DIESEL-01": ("SCOPE_1", "MOBILE_COMBUSTION"),
        "FUEL-NGAS-001": ("SCOPE_1", "STATIONARY_COMBUSTION"),
        "ELEC-COMP-001": ("SCOPE_3", "PURCHASED_GOODS"),
        "RAW-STEEL-001": ("SCOPE_3", "PURCHASED_GOODS"),
        "RAW-STEEL-002": ("SCOPE_3", "PURCHASED_GOODS"),
        "PKG-CARDB-01": ("SCOPE_3", "PURCHASED_GOODS"),
        "CHEM-SOLV-01": ("SCOPE_3", "PURCHASED_GOODS"),
        "OFFICE-PPR-01": ("SCOPE_3", "PURCHASED_GOODS"),
    }

    UNIT_CONVERSIONS = {
        "G": Decimal("0.001"),
        "KG": Decimal("1.0"),
        "TON": Decimal("1000.0"),
        "T": Decimal("1000.0"),
        "ML": Decimal("0.001"),
        "L": Decimal("1.0"),
        "M3": Decimal("1000.0"),
        "KWH": Decimal("1.0"),
        "MWH": Decimal("1000.0"),
        "GJ": Decimal("277.778"),
        "MJ": Decimal("0.277778"),
        "THERM": Decimal("29.3071"),
        "M": Decimal("0.001"),
        "KM": Decimal("1.0"),
        "MI": Decimal("1.60934"),
        "PC": Decimal("1.0"),
        "EA": Decimal("1.0"),
        "NIGHT": Decimal("1.0"),
        "NIGHTS": Decimal("1.0"),
    }

    NORMALIZED_UNITS = {
        "mass": "KG",
        "volume": "L",
        "energy": "KWH",
        "distance": "KM",
        "count": "PC",
        "hotel": "NIGHT",
    }

    def __init__(self, ingestion_job, performed_by=None):
        self.job = ingestion_job
        self.tenant = ingestion_job.tenant
        self.performed_by = performed_by
        self.stats = {
            "total": 0, "success": 0, "flagged": 0, "failed": 0, "errors": [],
        }

    @transaction.atomic
    def normalize_sap_records(self, raw_records):
        for raw in raw_records:
            self.stats["total"] += 1
            try:
                self._normalize_single_sap(raw)
                self.stats["success"] += 1
            except NormalizerError as e:
                self.stats["flagged"] += 1
                self.stats["errors"].append(f"SAP {raw.purchase_order_id}: {str(e)}")
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                self.stats["failed"] += 1
                self.stats["errors"].append(f"SAP {raw.purchase_order_id}: UNEXPECTED: {str(e)}\n{tb}")
        return self.stats

    @transaction.atomic
    def normalize_utility_records(self, raw_records):
        for raw in raw_records:
            self.stats["total"] += 1
            try:
                self._normalize_single_utility(raw)
                self.stats["success"] += 1
            except NormalizerError as e:
                self.stats["flagged"] += 1
                self.stats["errors"].append(f"Utility {raw.account_number}: {str(e)}")
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                self.stats["failed"] += 1
                self.stats["errors"].append(f"Utility {raw.account_number}: UNEXPECTED: {str(e)}\n{tb}")
        return self.stats

    @transaction.atomic
    def normalize_travel_records(self, raw_records):
        for raw in raw_records:
            self.stats["total"] += 1
            try:
                self._normalize_single_travel(raw)
                self.stats["success"] += 1
            except NormalizerError as e:
                self.stats["flagged"] += 1
                self.stats["errors"].append(f"Travel {raw.expense_report_id}: {str(e)}")
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                self.stats["failed"] += 1
                self.stats["errors"].append(f"Travel {raw.expense_report_id}: UNEXPECTED: {str(e)}\n{tb}")
        return self.stats

    def _normalize_single_sap(self, raw):
        location = self._resolve_location(
            sap_plant_code=raw.plant,
            sap_company_code=raw.company_code,
        )

        scope, activity_category = self._classify_sap_material(raw.material)

        raw_qty = self._safe_decimal(raw.order_quantity, "order_quantity")
        raw_unit = str(raw.order_unit).upper().strip() if raw.order_unit else ""

        if not raw_unit:
            raise NormalizerError("Empty order_unit")

        normalized_qty, normalized_unit = self._normalize_quantity(
            value=raw_qty,
            unit=raw_unit,
        )

        factor, factor_source, co2e = self._compute_co2e(
            material=raw.material,
            quantity=normalized_qty,
            unit=normalized_unit,
            scope=scope,
        )

        status, flag_reason = self._determine_sap_status(
            location, normalized_qty, co2e, raw.material, normalized_unit, raw.plant
        )

        net_price = self._safe_decimal(raw.net_price, "net_price") if raw.net_price else None

        activity = NormalizedActivity.objects.create(
            tenant=self.tenant,
            source_type="SAP_PROCUREMENT",
            ingestion_job=self.job,
            raw_sap_record=raw,
            canonical_location=location,
            activity_date=raw.creation_date,
            scope_category=scope,
            activity_category=activity_category,
            quantity=normalized_qty,
            quantity_unit=normalized_unit,
            emission_factor=factor,
            emission_factor_source=factor_source,
            co2e_kg=co2e,
            spend_amount=net_price,
            spend_currency=raw.document_currency,
            status=status,
            flag_reason=flag_reason,
            created_by=self.performed_by,
        )

        self._create_audit_log(activity, "CREATED", "Initial normalization from SAP")

    def _normalize_single_utility(self, raw):
        location = self._resolve_location(
            utility_account_number=raw.account_number,
            utility_meter_id=raw.meter_id,
        )

        scope, activity_category = self._classify_utility(raw.utility_type)

        raw_consumption = self._safe_decimal(raw.consumption, "consumption")
        raw_unit = str(raw.consumption_unit).upper().strip() if raw.consumption_unit else ""

        if not raw_unit:
            raise NormalizerError("Empty consumption_unit")

        normalized_qty, normalized_unit = self._normalize_quantity(
            value=raw_consumption,
            unit=raw_unit,
        )

        factor, factor_source, co2e = self._compute_co2e(
            material=raw.utility_type,
            quantity=normalized_qty,
            unit=normalized_unit,
            scope=scope,
        )

        status = "PENDING_REVIEW"
        flag_reason = None

        if not location:
            status = "FLAGGED"
            flag_reason = f"Unmapped utility account: {raw.account_number}"
        elif raw.billing_period_end < raw.billing_period_start:
            status = "FLAGGED"
            flag_reason = "Billing period end before start"
        elif not co2e:
            status = "FLAGGED"
            flag_reason = f"No emission factor for {raw.utility_type} / {normalized_unit}"

        total_cost = self._safe_decimal(raw.total_cost, "total_cost") if raw.total_cost else None

        activity = NormalizedActivity.objects.create(
            tenant=self.tenant,
            source_type=f"UTILITY_{raw.utility_type}",
            ingestion_job=self.job,
            raw_utility_record=raw,
            canonical_location=location,
            activity_date=raw.billing_period_end,
            scope_category=scope,
            activity_category=activity_category,
            quantity=normalized_qty,
            quantity_unit=normalized_unit,
            emission_factor=factor,
            emission_factor_source=factor_source,
            co2e_kg=co2e,
            spend_amount=total_cost,
            spend_currency=raw.cost_currency,
            status=status,
            flag_reason=flag_reason,
            created_by=self.performed_by,
        )

        self._create_audit_log(activity, "CREATED", "Initial normalization from utility CSV")

    def _normalize_single_travel(self, raw):
        location = self._resolve_location(
            travel_cost_center=raw.cost_center,
        )

        scope, activity_category = self._classify_travel(raw.travel_type)

        if raw.travel_type == "HOTEL":
            normalized_qty = Decimal(str(raw.number_of_nights or 1))
            normalized_unit = "NIGHT"
        else:
            if raw.distance_km:
                normalized_qty = self._safe_decimal(raw.distance_km, "distance_km")
                normalized_unit = "KM"
            else:
                normalized_qty = self._estimate_distance(
                    raw.origin_airport_code,
                    raw.destination_airport_code,
                )
                normalized_unit = "KM"

        travel_key = self._get_travel_factor_key(raw.travel_type, normalized_qty)
        factor, factor_source, co2e = self._compute_co2e(
            material=travel_key,
            quantity=normalized_qty,
            unit=normalized_unit,
            scope=scope,
        )

        status = "PENDING_REVIEW"
        flag_reason = None

        if not location:
            status = "FLAGGED"
            flag_reason = f"Unmapped travel cost center: {raw.cost_center}"
        elif not raw.distance_km and not raw.origin_airport_code:
            status = "FLAGGED"
            flag_reason = "Missing distance and airport codes — cannot estimate"
        elif not co2e:
            status = "FLAGGED"
            flag_reason = f"No emission factor for {raw.travel_type}"

        amount = self._safe_decimal(raw.amount, "amount")

        activity = NormalizedActivity.objects.create(
            tenant=self.tenant,
            source_type=f"TRAVEL_{raw.travel_type}",
            ingestion_job=self.job,
            raw_travel_record=raw,
            canonical_location=location,
            activity_date=raw.trip_date,
            scope_category=scope,
            activity_category=activity_category,
            quantity=normalized_qty,
            quantity_unit=normalized_unit,
            emission_factor=factor,
            emission_factor_source=factor_source,
            co2e_kg=co2e,
            spend_amount=amount,
            spend_currency=raw.currency,
            status=status,
            flag_reason=flag_reason,
            created_by=self.performed_by,
        )

        self._create_audit_log(activity, "CREATED", "Initial normalization from travel data")

    def _resolve_location(self, **kwargs):
        filters = {"tenant": self.tenant, "is_active": True}

        for key, value in kwargs.items():
            if value:
                filters[key] = value

        if len(filters) <= 2:
            return None

        try:
            return LocationMapping.objects.get(**filters)
        except LocationMapping.DoesNotExist:
            return None
        except LocationMapping.MultipleObjectsReturned:
            return None

    def _classify_sap_material(self, material):
        return self.MATERIAL_CLASSIFICATION.get(material, ("SCOPE_3", "PURCHASED_GOODS"))

    def _classify_utility(self, utility_type):
        mapping = {
            "ELECTRICITY": ("SCOPE_2", "PURCHASED_ELECTRICITY"),
            "NATURAL_GAS": ("SCOPE_1", "STATIONARY_COMBUSTION"),
            "WATER": ("SCOPE_3", "OTHER"),
            "STEAM": ("SCOPE_2", "PURCHASED_HEAT"),
        }
        return mapping.get(utility_type, ("SCOPE_3", "OTHER"))

    def _classify_travel(self, travel_type):
        mapping = {
            "FLIGHT": ("SCOPE_3", "BUSINESS_TRAVEL_AIR"),
            "HOTEL": ("SCOPE_3", "BUSINESS_TRAVEL_HOTEL"),
            "GROUND": ("SCOPE_3", "BUSINESS_TRAVEL_GROUND"),
            "RAIL": ("SCOPE_3", "BUSINESS_TRAVEL_RAIL"),
            "CAR_RENTAL": ("SCOPE_3", "BUSINESS_TRAVEL_GROUND"),
        }
        return mapping.get(travel_type, ("SCOPE_3", "BUSINESS_TRAVEL_GROUND"))

    def _normalize_quantity(self, value, unit):
        value = self._safe_decimal(value, "normalize_quantity value")

        unit_upper = str(unit).upper().strip()
        conversion = self.UNIT_CONVERSIONS.get(unit_upper)

        if not conversion:
            raise NormalizerError(f"Unknown unit for conversion: {unit}")

        conversion = self._safe_decimal(conversion, "conversion factor")

        normalized_value = (value * conversion).quantize(Decimal("0.000001"))

        if unit_upper in ["G", "KG", "TON", "T"]:
            target = self.NORMALIZED_UNITS["mass"]
        elif unit_upper in ["ML", "L", "M3"]:
            target = self.NORMALIZED_UNITS["volume"]
        elif unit_upper in ["KWH", "MWH", "GJ", "MJ", "THERM"]:
            target = self.NORMALIZED_UNITS["energy"]
        elif unit_upper in ["M", "KM", "MI"]:
            target = self.NORMALIZED_UNITS["distance"]
        elif unit_upper in ["PC", "EA", "NIGHT", "NIGHTS"]:
            target = self.NORMALIZED_UNITS.get("hotel" if "NIGHT" in unit_upper else "count")
        else:
            target = unit_upper

        return normalized_value, target

    def _compute_co2e(self, material, quantity, unit, scope):
        quantity = self._safe_decimal(quantity, "compute_co2e quantity")

        key = (material, unit)
        factor = self.EMISSION_FACTORS.get(key)

        if not factor:
            if scope == "SCOPE_2":
                factor = self.EMISSION_FACTORS.get(("ELECTRICITY", unit))
            elif scope == "SCOPE_3":
                # Try generic purchased goods factor for any unit
                factor = self.EMISSION_FACTORS.get(("PURCHASED_GOODS", unit))

        if not factor:
            return None, None, None

        factor = self._safe_decimal(factor, "emission factor")

        co2e = (quantity * factor).quantize(Decimal("0.000001"))
        source = "Simplified prototype factor (DEFRA/EPA in production)"

        return factor, source, co2e

    def _get_travel_factor_key(self, travel_type, distance_km):
        distance_km = self._safe_decimal(distance_km, "distance_km")
        if travel_type == "FLIGHT":
            return "FLIGHT_LONG_HAUL" if distance_km > 1500 else "FLIGHT_SHORT_HAUL"
        elif travel_type == "HOTEL":
            return "HOTEL"
        elif travel_type == "RAIL":
            return "GROUND_RAIL"
        else:
            return "GROUND_CAR"

    def _estimate_distance(self, origin, destination):
        DISTANCES = {
            ("BER", "LHR"): Decimal("932"),
            ("BER", "CDG"): Decimal("878"),
            ("BER", "JFK"): Decimal("6385"),
            ("BER", "DXB"): Decimal("4615"),
            ("LHR", "JFK"): Decimal("5540"),
            ("CDG", "JFK"): Decimal("5834"),
            ("FRA", "LHR"): Decimal("808"),
            ("MUC", "LHR"): Decimal("942"),
        }

        if not origin or not destination:
            raise NormalizerError("Missing airport codes for distance estimation")

        origin = str(origin).upper()
        destination = str(destination).upper()

        dist = DISTANCES.get((origin, destination)) or DISTANCES.get((destination, origin))

        if not dist:
            dist = Decimal("1000")

        return dist

    def _determine_sap_status(self, location, normalized_qty, co2e, material, normalized_unit, plant):
        status = "PENDING_REVIEW"
        flag_reason = None

        if not location:
            status = "FLAGGED"
            flag_reason = f"Unmapped SAP Plant: {plant}"
        elif normalized_qty <= 0:
            status = "FLAGGED"
            flag_reason = "Zero or negative quantity after normalization"
        elif not co2e:
            status = "FLAGGED"
            flag_reason = f"No emission factor for {material} / {normalized_unit}"
        elif co2e > Decimal("100000"):
            status = "FLAGGED"
            flag_reason = f"CO2e suspiciously high: {co2e} kg"

        return status, flag_reason

    def _create_audit_log(self, activity, action, reason):
        ActivityAuditLog.objects.create(
            tenant=self.tenant,
            activity=activity,
            action=action,
            performed_by=self.performed_by,
            snapshot={
                "id": str(activity.id),
                "source_type": activity.source_type,
                "scope_category": activity.scope_category,
                "activity_category": activity.activity_category,
                "quantity": str(activity.quantity),
                "quantity_unit": activity.quantity_unit,
                "co2e_kg": str(activity.co2e_kg) if activity.co2e_kg else None,
                "status": activity.status,
                "flag_reason": activity.flag_reason,
            },
            reason=reason,
        )

    @staticmethod
    def _safe_decimal(value, context="value"):
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))

        cleaned = str(value).replace(",", "").replace(" ", "").strip()
        if not cleaned:
            return Decimal("0")

        try:
            return Decimal(cleaned)
        except InvalidOperation:
            raise NormalizerError(f"Cannot convert {context} to Decimal: {value!r} (type: {type(value).__name__})")