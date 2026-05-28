# SOURCES.md — Real-World Research & Sample Data

## 1. SAP Procurement — OData V4

### What We Researched

SAP S/4HANA exposes procurement data via OData V4 services. The primary service for purchase orders is:
- **Service:** `API_PURCHASEORDER_PROCESS_SRV`
- **Entity:** `PurchaseOrder` (header) + `PurchaseOrderItem` (line items)
- **Documentation:** SAP API Business Hub — Purchase Order Integration

### Real-World Payload Structure

```json
{
  "PurchaseOrder": "4500000001",
  "CompanyCode": "1000",
  "PurchasingOrganization": "1710",
  "PurchaseOrderType": "NB",
  "Supplier": "S0001",
  "SupplierName": "ThyssenKrupp Materials",
  "CreationDate": "2025-03-15",
  "DocumentCurrency": "EUR",
  "to_PurchaseOrderItem": [
    {
      "PurchaseOrderItem": "00010",
      "Plant": "1200",
      "Material": "RAW-STEEL-001",
      "MaterialDescription": "Raw Steel Sheet",
      "OrderQuantity": "500.000",
      "PurchaseOrderQuantityUnit": "KG",
      "NetPriceAmount": "1250.00",
      "NetPriceQuantity": "1",
      "NetPriceQuantityUnit": "KG"
    }
  ]
}
```

### What We Learned

- SAP returns quantities as **strings with 3 decimal places** (e.g., `"500.000"`)
- `CompanyCode` (BUKRS) is local to the SAP instance — meaningless without context
- `Plant` (Werks) is the key operational location code
- German configurations often have German descriptions
- Custom append structures (Z-fields) are common but unpredictable
- OData pagination uses `$skip` and `$top`; large datasets require batching

### Our Sample Data

We fabricated JSON responses that mirror this structure:
- Realistic field names (`PurchaseOrder`, `CompanyCode`, `Plant`, `Material`, etc.)
- Quantities as strings with 3 decimal places
- ISO currency codes (`EUR`, `USD`)
- Plant codes from `1000` to `2000`
- Material codes from our `MATERIAL_MASTER` lookup

### What Would Break in Real Deployment

| Issue | Why | Mitigation |
|-------|-----|------------|
| Custom Z-fields | Client adds custom fields to PO structure | Dynamic JSON parsing, schema registry |
| OAuth2 token expiry | SAP Gateway uses OAuth2 with 1-hour tokens | Token refresh logic in client |
| CSRF tokens | State-changing operations require CSRF | Fetch token before POST/PUT |
| Rate limiting | SAP Gateway limits requests per minute | Exponential backoff, request queuing |
| Language variants | Descriptions in German, French, etc. | UTF-8 handling, translation layer |
| Plant code changes | M&A or reorganization changes codes | Versioned location mappings |

---

## 2. Utility Data — CSV Portal Export

### What We Researched

Commercial utility portals (E.ON, EnBW, British Gas, Con Edison) provide CSV exports with:
- Account number and meter ID
- Billing period start/end dates
- Consumption in kWh, therms, or m³
- Total cost and currency
- Tariff/rate schedule code

### Real-World CSV Format

```csv
AccountNumber,MeterID,ServiceType,BillingPeriodStart,BillingPeriodEnd,Usage,Unit,TotalAmount,Currency,RateSchedule
881-221-001,MTR-4412,ELECTRICITY,2025-01-01,2025-01-31,15420.50,KWH,1847.45,EUR,IND-SM-01
881-221-001,MTR-4412,ELECTRICITY,2025-02-01,2025-02-28,14200.30,KWH,1701.23,EUR,IND-SM-01
```

### What We Learned

- **No standard format** — each utility uses different column names
- **Date formats vary** — `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY` all appear
- **Delimiters vary** — comma in US, semicolon in Germany
- **Encoding issues** — Windows-1252 vs UTF-8
- **Billing periods rarely align** with calendar months
- **Estimated readings** are not always marked clearly

### Our Sample Data

`sample_data/electricity_bills.csv`:
- 5 rows across 2 accounts
- Mixed utility types (electricity, gas)
- Standard ISO date format (`YYYY-MM-DD`)
- Comma delimiter, UTF-8 encoding

### What Would Break in Real Deployment

| Issue | Why | Mitigation |
|-------|-----|------------|
| New column names | Utility portal redesigns CSV export | Fuzzy header matching, ML-based column detection |
| New units | e.g., `CCf` (hundreds of cubic feet) for gas | Extensible unit mapping table |
| Sub-meters | One account with multiple meters | Meter-level granularity in model |
| Estimated vs actual | Estimated readings skew emissions | Flag estimated readings for review |
| Time-of-use | Peak/off-peak/shoulder rates | Add time-of-use breakdown fields |
| Multi-currency | Subsidiary bills in local currency | Currency conversion with date-specific rates |

---

## 3. Corporate Travel — Concur/Navan API

### What We Researched

Travel expense platforms expose data via REST APIs:
- **Concur:** `Expense` API v3.0 — `GET /api/v3.0/expense/expensereports`
- **Navan:** Expenses API — `GET /v1/expenses`
- **Common fields:** expense ID, employee, cost center, trip date, amount, currency, category

### Real-World API Response (Concur-style)

```json
{
  "ID": "EXP-2025-004412",
  "EmployeeName": "John Smith",
  "EmployeeID": "E08912",
  "CostCenter": "CC-BER-01",
  "TripDate": "2025-02-15",
  "TransactionAmount": 245.00,
  "TransactionCurrencyCode": "EUR",
  "ExpenseTypeName": "Airfare",
  "FlightLegs": [
    {
      "OriginAirport": "BER",
      "DestinationAirport": "LHR",
      "FlightDistance": 932
    }
  ]
}
```

### What We Learned

- **Distance is often missing** — only airport codes provided
- **Expense category is text** — "Airfare", "Hotel", "Car Rental" (not standardized codes)
- **Ground transport is ambiguous** — taxi, rideshare, rental car all map to "Ground"
- **Hotel data lacks granularity** — no star rating, no room type
- **Booking class affects emissions** — economy vs business vs first class
- **Multi-leg flights** complicate distance calculation

### Our Sample Data

`sample_data/flights.json`:
- 3 records: flight with distance, flight without distance (airport codes only), hotel
- Realistic fields: `ExpenseReportID`, `CostCenter`, `TravelType`, `TripDate`
- Airport codes for distance estimation fallback

### What Would Break in Real Deployment

| Issue | Why | Mitigation |
|-------|-----|------------|
| OAuth2 complexity | Concur requires partner app registration | Dedicated OAuth2 client with refresh logic |
| Rate limiting | APIs limit requests per minute | Request queuing, caching |
| Missing distance | Not all platforms provide distance | Great-circle distance calculation from airport codes |
| Ground transport modes | "Ground" could be taxi, bus, rideshare | Employee survey or expense description NLP |
| Hotel star ratings | Emission factors vary by hotel class | Integration with booking platform (Booking.com API) |
| Rail vs air ambiguity | Some rail bookings coded as "Airfare" | Route validation against rail network data |
| Multi-currency trips | Expense in EUR, reimbursement in USD | Currency conversion at transaction date |

---

## Summary: What Our Sample Data Demonstrates

| Source | Realism Claim | Evidence |
|--------|--------------|----------|
| SAP | Structure matches OData V4 spec | Field names, nested entities, string quantities |
| Utility | Matches portal export patterns | Column names, date formats, unit variations |
| Travel | Matches Concur/Navan API shape | Expense ID, cost center, airport codes, booking class |

All sample data is **fabricated but structurally realistic**. We can defend every field name and data type by referencing actual API documentation.
