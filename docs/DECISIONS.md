# DECISIONS.md — Architectural Decisions

## 1. SAP OData V4 for Procurement

**What we chose:** Simulated SAP OData V4 `API_PURCHASEORDER_PROCESS_SRV` with realistic field structure.

**Why:** Real SAP S/4HANA exposes purchase orders via OData V4. The entity structure (`PurchaseOrder`, `PurchaseOrderItem`) with fields like `CompanyCode`, `Plant`, `Material`, `OrderQuantity` is standard across SAP implementations. We simulate the payload shape but preserve the structural realism — quantities as strings with 3 decimal places, German plant codes, ISO currency.

**What we ignored:**
- IDoc flat file format (legacy, being phased out)
- BAPI direct calls (require ABAP knowledge, harder to mock)
- Custom append structures (Z-fields) — out of scope for prototype

**What we'd ask the PM:**
- "Does the client use S/4HANA or ECC?" (affects available OData services)
- "Are there custom Z-fields we need to capture?"
- "Do they want incremental pulls (delta) or full snapshots?"

---

## 2. CSV Upload for Utility Data

**What we chose:** Drag-and-drop CSV upload with auto-detection of delimiters, encodings, and date formats.

**Why:** Facilities teams download CSV exports from utility portals. This is the actual workflow — there is no standard utility API. PDF parsing would require OCR and is unreliable. Portal scraping breaks when portals redesign.

**What we ignored:**
- PDF bill parsing (too complex for 4-day prototype)
- Real-time smart meter APIs (rarely available for commercial accounts)
- Time-of-use breakdown (peak/off-peak rates)

**What we'd ask the PM:**
- "Does the facilities team already have standardized CSV templates, or do we need to handle arbitrary portal exports?"
- "Do they need meter-level granularity or account-level aggregation?"

---

## 3. Simulated Travel API

**What we chose:** Simulated Concur/Navan-style JSON with `ExpenseReportID`, `CostCenter`, `TravelType`, `OriginAirportCode`, `DistanceKm`.

**Why:** Travel platforms (Concur, Navan, Expensify) expose expense data via REST APIs. The shape varies but consistently includes: expense ID, employee, cost center, trip date, amount, and travel category. We simulate the common denominator.

**What we ignored:**
- Real Concur API integration (requires OAuth2 + partner approval)
- Hotel star rating emission factors (would need third-party data)
- Ground transport mode breakdown (taxi vs rideshare vs rental)

**What we'd ask the PM:**
- "Which travel platform does the client use?" (Concur API is different from Navan)
- "Do they book flights through a TMC that provides CO2 data?"

---

## 4. Synchronous Ingestion

**What we chose:** Synchronous request-response for all ingestion endpoints.

**Why:** 4-day constraint. Celery + Redis adds deployment complexity (extra service, broker config, result backend). For prototype volumes (< 500 records), synchronous is acceptable.

**Tradeoff:** Large CSVs block the HTTP request. In production, we'd use Celery with Redis/RabbitMQ for background processing.

**What we'd ask the PM:**
- "What's the expected monthly record volume?" (determines async need)
- "Do analysts need real-time feedback, or is 'processing' status acceptable?"

---

## 5. Django Default User Model

**What we chose:** `django.contrib.auth.models.User` instead of custom user model.

**Why:** No tenant-scoped permissions or role-based access needed for prototype. JWT authentication via `djangorestframework-simplejwt` provides token-based auth without custom user fields.

**Tradeoff:** Cannot add tenant-specific fields to User. In production, we'd extend `AbstractUser` with `tenant` FK and role fields.

---

## 6. SQLite for Local, PostgreSQL for Production

**What we chose:** `dj-database-url` with `DATABASE_URL` environment variable.

**Why:** SQLite requires zero setup for local development. PostgreSQL is production-grade. One config switch via env var handles both.

**What we'd ask the PM:**
- "Do they have a preferred cloud database?" (AWS RDS, Cloud SQL, etc.)
- "Is multi-region replication needed for EU data residency?"
