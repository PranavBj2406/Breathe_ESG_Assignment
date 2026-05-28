# TRADEOFFS.md — What We Deliberately Did Not Build

## 1. Asynchronous Job Queue (Celery + Redis)

**What it is:** Background processing for long-running ingestion jobs using Celery workers and Redis as message broker.

**Why we skipped it:**
- Adds two new services to deploy and monitor (Celery worker, Redis)
- Increases local development complexity (need Redis running)
- For prototype volumes (< 500 records per job), synchronous processing completes in < 5 seconds
- Time cost: ~2 hours to configure + debug

**What breaks without it:**
- Uploading a 10,000-row utility CSV blocks the HTTP request for 30+ seconds
- No retry logic for transient SAP connection failures
- Cannot show "processing" status to analyst — they wait for the request

**When we'd add it:**
- Monthly volume exceeds 10,000 records
- Need scheduled nightly SAP pulls
- Want retry with exponential backoff for API failures

---

## 2. PDF Bill Parsing for Utilities

**What it is:** Extracting structured data from PDF utility bills using pdfplumber or OCR.

**Why we skipped it:**
- PDF layouts vary wildly by utility provider (no standard format)
- OCR introduces errors that require manual correction anyway
- Facilities teams already download CSVs from portals — PDF is the exception
- Time cost: ~4 hours to build a fragile parser + 2 hours to test edge cases

**What breaks without it:**
- Clients who only receive paper/PDF bills cannot onboard
- Need manual data entry for PDF-only utilities

**When we'd add it:**
- Client explicitly requires PDF handling
- We have 50+ PDF samples to train a robust parser
- Budget for third-party PDF extraction API (e.g., DocParser)

---

## 3. Real-Time Emission Factor API Integration

**What it is:** Live lookups to DEFRA, EPA GHG Emission Factors Hub, or Climeworks for location-specific and time-varying emission factors.

**Why we skipped it:**
- Requires API keys, rate limiting, and caching strategy
- DEFRA factors change annually — not real-time anyway
- For prototype, hardcoded factors demonstrate the calculation pipeline
- Time cost: ~3 hours to integrate + ongoing maintenance

**What breaks without it:**
- Emission calculations use generic averages, not client-specific factors
- Grid electricity factors are EU-wide average, not country-specific
- No supplier-specific factors for purchased goods

**When we'd add it:**
- Client requires audit-grade accuracy
- Operating in markets with strict emission factor regulations (e.g., UK SECR)
- Need to demonstrate year-over-year improvement using updated factors

---

## Honorable Mentions (Also Not Built)

| Feature | Why Skipped | Impact |
|--------|-------------|--------|
| React frontend (full) | 1-day constraint; DRF browsable API suffices for demo | Analysts need a UI eventually |
| Multi-entity rollups | Holding company with multiple BUKRS codes not in scope | Cannot split emissions by legal entity |
| Supplier master data | No supplier database to link emission factors | Purchased goods use generic factors |
| Currency conversion | All financial data kept in original currency | Cannot compare spend across currencies |
| Time-of-use electricity | No peak/off-peak breakdown | Misses demand-shifting opportunities |
| Data validation rules engine | Hardcoded rules instead of configurable | Adding new rules requires code changes |
