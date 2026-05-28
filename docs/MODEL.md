# MODEL.md — Data Model & Architecture

## Overview

The Breathe ESG platform uses a **two-layer data model**:
1. **Raw Ingestion Layer** — immutable, source-specific records
2. **Normalized Core Layer** — unified, analyst-reviewable emission activities

This design separates "what came in" from "what we analyze," enabling audit trails, reprocessing, and cross-source correlation.

---

## Entity Relationship Diagram

```
Tenant (1)
  ├── LocationMapping (N) — cross-source master data aliases
  ├── IngestionSource (N) — pre-configured data endpoints
  │     └── IngestionJob (N) — single ingestion run
  │           ├── RawSAPRecord (N) — immutable SAP payload
  │           ├── RawUtilityRecord (N) — immutable CSV rows
  │           ├── RawTravelRecord (N) — immutable API/CSV rows
  │           └── NormalizedActivity (N) — unified review table
  │                 └── ActivityAuditLog (N) — immutable action log
```

---

## Multi-Tenancy

Every table has a `tenant_id` FK to `Tenant`. No global records exist. Tenant binding happens at the **ingestion configuration layer**, not in the raw payload. SAP, utility portals, and travel platforms do not emit global company identifiers — we bind sources to tenants via `IngestionSource.tenant`.

---

## Source-of-Truth Tracking

Every `NormalizedActivity` row traces back to exactly one raw record via polymorphic FKs:
- `raw_sap_record` → `RawSAPRecord`
- `raw_utility_record` → `RawUtilityRecord`
- `raw_travel_record` → `RawTravelRecord`

A database `CHECK` constraint ensures exactly one is non-null. The `ingestion_job` FK provides the run-level context (who triggered it, when, which source config).

---

## Scope 1/2/3 Categorization

Classification happens during normalization based on:
- **Material type** (SAP) — `FUEL-DIESEL-01` → Scope 1 Mobile Combustion
- **Utility type** — `ELECTRICITY` → Scope 2 Purchased Electricity
- **Travel type** — `FLIGHT` → Scope 3 Business Travel Air

The mapping is explicit in `NormalizerService.MATERIAL_CLASSIFICATION` and related methods. Analysts can override via the review dashboard.

---

## Unit Normalization

Raw units are converted to normalized units during ingestion:

| Dimension | Raw Units | Normalized Unit |
|-----------|-----------|-----------------|
| Mass | G, KG, TON, T | KG |
| Volume | ML, L, M3 | L |
| Energy | KWH, MWH, GJ, MJ, THERM | KWH |
| Distance | M, KM, MI | KM |
| Count | PC, EA | PC |
| Hotel | NIGHT, NIGHTS | NIGHT |

Conversion factors are hardcoded in `NormalizerService.UNIT_CONVERSIONS`. In production, these would be configurable per tenant.

---

## Audit Trail

Two mechanisms:
1. **Versioning on NormalizedActivity** — `version`, `previous_version`, `change_reason` track row edits
2. **ActivityAuditLog** — immutable JSON snapshots of every approve/flag/reject/lock action

No hard deletes. `is_deleted` + `deleted_at` provide soft delete for audit preservation.

---

## Indexes

| Table | Index | Purpose |
|-------|-------|---------|
| `normalized_activities` | `(tenant, status, activity_date)` | Dashboard queries |
| `normalized_activities` | `(tenant, scope_category, activity_category)` | Scope filtering |
| `raw_sap_records` | `(tenant, company_code, plant)` | Location mapping lookups |
| `raw_utility_records` | `(tenant, account_number, billing_period_start)` | Deduplication |
| `activity_audit_logs` | `(tenant, activity, -performed_at)` | Audit history |

---

## What Would Change in Production

- **Partitioning**: `normalized_activities` partitioned by `activity_date` for scale
- **Emission factor tables**: Replace hardcoded factors with DEFRA/EPA API lookups
- **Supplier-specific factors**: Add `SupplierEmissionFactor` table
- **Real-time streaming**: Kafka/Kinesis for high-volume SAP IDoc streams
- **Location mapping UI**: Self-service mapping tool for analysts
