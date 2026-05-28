"""
Utility CSV Parser — Handles real-world portal export formats.

Researches:
- Typical utility portal CSV exports contain: AccountNumber, MeterID, 
  BillingPeriodStart, BillingPeriodEnd, Consumption, ConsumptionUnit, 
  TotalCost, Currency, TariffCode
- Common issues: mixed date formats, inconsistent delimiters (comma vs semicolon),
  encoding problems (UTF-8 vs Windows-1252), missing headers, extra blank rows
- Billing periods rarely align with calendar months
- Units vary by region: KWH, MWH, THERM, MJ, M3

What we handle:
- UTF-8 and Windows-1252 encoding fallback
- Comma and semicolon delimiter auto-detection
- Flexible date parsing (YYYY-MM-DD, DD/MM/YYYY, MM-DD-YYYY)
- Required field validation with clear error messages
- Duplicate detection via checksum
- Unit normalization mapping

What we do NOT handle (documented in TRADEOFFS.md):
- PDF bill parsing
- Portal scraping (would need Selenium/Playwright)
- Real-time API connections to utility providers (rarely available)
- Time-of-use breakdown (peak/off-peak rates)

What would break in real deployment:
- Portal changes CSV column names without notice
- New units not in our mapping (e.g., CCf for gas)
- Multi-meter accounts with sub-meters
- Estimated vs actual readings not distinguished
- Currency conversion if bills are in local subsidiary currency
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

import pandas as pd
from django.core.exceptions import ValidationError


class UtilityCSVParser:
    """
    Parse utility portal CSV exports into structured records.
    """

    # Standard unit mappings to normalized units
    UNIT_NORMALIZATION = {
        # Electricity
        "KWH": "KWH",
        "KWHRS": "KWH",
        "KILOWATT HOUR": "KWH",
        "KILOWATT-HOUR": "KWH",
        "MWH": "MWH",
        "MEGAWATT HOUR": "MWH",
        "MEGAWATT-HOUR": "MWH",
        # Gas
        "THERM": "THERM",
        "THERMS": "THERM",
        "M3": "M3",
        "CUBIC METER": "M3",
        "CUBIC METERS": "M3",
        "M³": "M3",
        "MJ": "MJ",
        "GJ": "GJ",
        # Water
        "GALLON": "GALLON",
        "GALLONS": "GALLON",
        "LITER": "LITER",
        "LITERS": "LITER",
        "L": "LITER",
    }

    # Required columns (case-insensitive matching)
    REQUIRED_COLUMNS = {
        "account_number": ["accountnumber", "account number", "account_no", "account no", "acct_num"],
        "billing_period_start": ["billingperiodstart", "billing period start", "start date", "period_start", "from"],
        "billing_period_end": ["billingperiodend", "billing period end", "end date", "period_end", "to"],
        "consumption": ["consumption", "usage", "total consumption", "energy consumed", "kwh"],
        "consumption_unit": ["consumptionunit", "consumption unit", "unit", "units", "uom", "unit of measure"],
    }

    # Optional columns
    OPTIONAL_COLUMNS = {
        "meter_id": ["meterid", "meter id", "meter_no", "meter number"],
        "utility_type": ["utilitytype", "utility type", "service type", "commodity"],
        "total_cost": ["totalcost", "total cost", "amount", "bill amount", "total amount"],
        "currency": ["currency", "curr", "ccy"],
        "tariff_code": ["tariffcode", "tariff code", "rate schedule", "tariff"],
    }

    def __init__(self, file_obj):
        """
        Args:
            file_obj: Django UploadedFile or file-like object
        """
        self.file_obj = file_obj
        self.normalized_columns = {}
        self.warnings = []

    def parse(self) -> list[dict]:
        """
        Main entry point. Returns list of validated, normalized records.

        Raises:
            ValidationError: If file is unreadable or missing required columns
        """
        # Try UTF-8 first, fallback to Windows-1252
        content = self._read_file()

        # Detect delimiter
        delimiter = self._detect_delimiter(content)

        # Parse CSV
        try:
            df = pd.read_csv(
                StringIO(content),
                delimiter=delimiter,
                skipinitialspace=True,
                dtype=str,  # Read everything as string first
                keep_default_na=False,
            )
        except pd.errors.EmptyDataError:
            raise ValidationError("CSV file is empty")
        except pd.errors.ParserError as e:
            raise ValidationError(f"Could not parse CSV: {str(e)}")

        # Clean column names
        df = self._clean_column_names(df)

        # Map columns to standard names
        self._map_columns(df)

        # Validate required columns present
        self._validate_required_columns()

        # Remove completely empty rows
        df = df.dropna(how="all")

        if df.empty:
            raise ValidationError("No data rows found in CSV after removing empty rows")

        # Parse each row
        records = []
        for idx, row in df.iterrows():
            try:
                record = self._parse_row(row, row_num=idx + 2)  # +2 for header + 1-indexing
                record["_row_number"] = idx + 2
                records.append(record)
            except ValidationError as e:
                self.warnings.append(f"Row {idx + 2}: {str(e)}")

        return records

    def _read_file(self) -> str:
        """Read file content, trying multiple encodings."""
        self.file_obj.seek(0)
        raw = self.file_obj.read()

        for encoding in ["utf-8", "utf-8-sig", "windows-1252", "iso-8859-1"]:
            try:
                if isinstance(raw, bytes):
                    return raw.decode(encoding)
                return raw
            except UnicodeDecodeError:
                continue

        raise ValidationError("Could not decode file. Tried UTF-8, Windows-1252, ISO-8859-1.")

    def _detect_delimiter(self, content: str) -> str:
        """Auto-detect CSV delimiter."""
        first_line = content.split("\n")[0]
        semicolon_count = first_line.count(";")
        comma_count = first_line.count(",")
        return ";" if semicolon_count > comma_count else ","

    def _clean_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names: lowercase, strip whitespace, replace spaces."""
        df.columns = [
            str(col).strip().lower().replace(" ", "").replace("_", "")
            for col in df.columns
        ]
        return df

    def _map_columns(self, df: pd.DataFrame):
        """Map input columns to standard internal names."""
        all_mappings = {**self.REQUIRED_COLUMNS, **self.OPTIONAL_COLUMNS}

        for standard_name, possible_names in all_mappings.items():
            for possible in possible_names:
                if possible in df.columns:
                    self.normalized_columns[standard_name] = possible
                    break

    def _validate_required_columns(self):
        """Ensure all required columns were found."""
        missing = []
        for standard_name in self.REQUIRED_COLUMNS:
            if standard_name not in self.normalized_columns:
                missing.append(standard_name)

        if missing:
            available = ", ".join(self.normalized_columns.keys())
            raise ValidationError(
                f"Missing required columns: {', '.join(missing)}. "
                f"Detected columns: {available}"
            )

    def _parse_row(self, row: pd.Series, row_num: int) -> dict:
        """Parse and validate a single row."""
        record = {}

        # Account number (required)
        account = str(row[self.normalized_columns["account_number"]]).strip()
        if not account:
            raise ValidationError("Account number is empty")
        record["account_number"] = account

        # Meter ID (optional)
        if "meter_id" in self.normalized_columns:
            record["meter_id"] = str(row[self.normalized_columns["meter_id"]]).strip() or None
        else:
            record["meter_id"] = None

        # Utility type (optional, default to ELECTRICITY if not specified)
        if "utility_type" in self.normalized_columns:
            raw_type = str(row[self.normalized_columns["utility_type"]]).strip().upper()
            record["utility_type"] = self._normalize_utility_type(raw_type)
        else:
            record["utility_type"] = "ELECTRICITY"

        # Dates (required)
        start_raw = str(row[self.normalized_columns["billing_period_start"]]).strip()
        end_raw = str(row[self.normalized_columns["billing_period_end"]]).strip()

        record["billing_period_start"] = self._parse_date(start_raw)
        record["billing_period_end"] = self._parse_date(end_raw)

        if record["billing_period_end"] < record["billing_period_start"]:
            raise ValidationError(
                f"End date ({end_raw}) is before start date ({start_raw})"
            )

        # Consumption (required)
        consumption_raw = str(row[self.normalized_columns["consumption"]]).strip()
        consumption_raw = consumption_raw.replace(",", "").replace("'", "")
        try:
            record["consumption"] = Decimal(consumption_raw)
        except InvalidOperation:
            raise ValidationError(f"Invalid consumption value: '{consumption_raw}'")

        if record["consumption"] < 0:
            raise ValidationError(f"Negative consumption: {record['consumption']}")

        # Unit (required)
        unit_raw = str(row[self.normalized_columns["consumption_unit"]]).strip().upper()
        record["consumption_unit"] = self._normalize_unit(unit_raw)
        if not record["consumption_unit"]:
            raise ValidationError(f"Unknown unit: '{unit_raw}'")

        # Cost (optional)
        if "total_cost" in self.normalized_columns:
            cost_raw = str(row[self.normalized_columns["total_cost"]]).strip()
            cost_raw = cost_raw.replace(",", "").replace("'", "")
            if cost_raw:
                try:
                    record["total_cost"] = Decimal(cost_raw)
                except InvalidOperation:
                    self.warnings.append(f"Row {row_num}: Invalid cost value '{cost_raw}', set to null")
                    record["total_cost"] = None
            else:
                record["total_cost"] = None
        else:
            record["total_cost"] = None

        # Currency (optional)
        if "currency" in self.normalized_columns:
            record["currency"] = str(row[self.normalized_columns["currency"]]).strip().upper() or None
        else:
            record["currency"] = None

        # Tariff (optional)
        if "tariff_code" in self.normalized_columns:
            record["tariff_code"] = str(row[self.normalized_columns["tariff_code"]]).strip() or None
        else:
            record["tariff_code"] = None

        # Compute checksum for deduplication
        record["_checksum"] = self._compute_checksum(record)

        return record

    def _parse_date(self, date_str: str) -> datetime.date:
        """Parse date from multiple formats."""
        date_str = date_str.strip()

        formats = [
            "%Y-%m-%d",      # 2025-01-15
            "%d/%m/%Y",      # 15/01/2025
            "%m/%d/%Y",      # 01/15/2025
            "%d-%m-%Y",      # 15-01-2025
            "%m-%d-%Y",      # 01-15-2025
            "%Y%m%d",        # 20250115
            "%d.%m.%Y",      # 15.01.2025
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        raise ValidationError(f"Unrecognized date format: '{date_str}'")

    def _normalize_unit(self, unit: str) -> str:
        """Map various unit strings to normalized unit."""
        unit_clean = unit.strip().upper().replace(" ", "").replace("-", "").replace("_", "")
        return self.UNIT_NORMALIZATION.get(unit_clean, None)

    def _normalize_utility_type(self, raw: str) -> str:
        """Map utility type strings to standard values."""
        mapping = {
            "ELECTRICITY": "ELECTRICITY",
            "ELEC": "ELECTRICITY",
            "ELECTRIC": "ELECTRICITY",
            "POWER": "ELECTRICITY",
            "NATURAL_GAS": "NATURAL_GAS",
            "GAS": "NATURAL_GAS",
            "NATURALGAS": "NATURAL_GAS",
            "NG": "NATURAL_GAS",
            "WATER": "WATER",
            "STEAM": "STEAM",
            "HEAT": "STEAM",
        }
        return mapping.get(raw, "OTHER")

    @staticmethod
    def _compute_checksum(record: dict) -> str:
        """SHA-256 for deduplication."""
        canonical = json.dumps(record, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get_warnings(self) -> list[str]:
        """Return non-fatal warnings from parsing."""
        return self.warnings