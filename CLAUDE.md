# USGS Hydrographer Toolbox — Project Notes for Claude

## Project Overview

A Django web application providing specialized tools for USGS hydrographers. Pulls data
from the USGS Water Services REST API and a Novastar ALERT2 telemetry system, with user
accounts, saved configurations, and persistent site relationship data.

---

## Tech Stack

- **Framework:** Django with PostgreSQL
- **Auth:** `django-allauth` (v65.x) with Microsoft OAuth; custom user model in `accounts`;
  mandatory email verification; `SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True`,
  `VERIFIED_EMAIL = True` in provider config (required to skip re-verification)
- **Email:** Brevo SMTP (`smtp-relay.brevo.com`, port 587); SMTP login is
  `a6e7f5001@smtp-brevo.com` (NOT the account Gmail) — set via `BREVO_SMTP_LOGIN` env var
- **Deployment:** Railway — `DATABASE_URL` env var; `Procfile` runs `migrate` +
  `collectstatic` on release, `gunicorn` on web
- **Static files:** WhiteNoise in production; `STATIC_ROOT = BASE_DIR / 'staticfiles'`
- **Data:** Polars (time-series), Plotly (charts)
- **AI:** Anthropic API (`claude-opus-4-5`), streamed via SSE, gated by
  `analysis.can_use_ai_assist` permission
- **USGS parameters:** `00060` discharge (cfs), `00065` gage height (ft),
  `00045` precipitation (inches, incremental)

---

## App Structure

```
accounts/         # Custom user model, django-allauth + Microsoft OAuth
sites/            # USGS site models (label: usgs_sites), site relationships, Novastar locators
water_balance/    # Water balance / flow plotter
alert2/           # ALERT2 / Novastar dashboard
analysis/         # Station analysis report authoring
rating_developer/ # Rating curve development
approval/         # Approval checklist
alert2_parser/    # ALERT2 IND packet decoder
reports/          # Shared report saving (planned, not yet built)
```

**Important:** `sites` app uses Django label `usgs_sites` to avoid conflict with
`django.contrib.sites`. All FK references use `'usgs_sites.Site'`.

---

## Data Models

### `accounts`
- **User** — extends `AbstractUser`; adds `email` (unique) and `tier` (`basic`/`advanced`)
- `basic` tier: Water Balance, ALERT2, Approval, ALERT2 Parser
- `advanced` tier: all tools (adds Rating Developer and Station Analysis)
- Staff/superuser always advanced; `/accounts/admin-tools/users/` for tier management
- `advanced_required` decorator in `accounts/decorators.py`

### `sites` (label: `usgs_sites`)
- **Site** — cached USGS site; auto-populated via `get_or_fetch()`; stores
  `transmit_interval_hours`, `transmit_offset_minutes` for ALERT2
- **SiteRelationship** — upstream→downstream link with `offset_minutes`; per-user
- **LocatorGroup** — named group of Novastar point locators not tied to a USGS site
- **NovaPointLocator** — maps a Novastar point locator to a `Site` or `LocatorGroup`

### `water_balance`
- **FlowBalanceConfig** — saved plot config; `comparison_sites` JSONField (list of
  `{site_no, offset_minutes, discharge_offset, offset_type, operation, group}`)

### `analysis`
- **AnalysisReport** — per `(user, site, period_start, period_end)` unique; stores
  `section_data` JSON, `is_complete`, `prior_period_analysis`
- **PrecipCalibration** — tipping-bucket calibration linked to a report
- **PrecipComparisonSite** / **StageQComparisonSite** — comparison USGS sites per report

### `rating_developer`
- **RatingConfig** — `user`, `site`, `name`, `use_manual_rating`, `manual_rating_text`,
  `hidden_measurement_nos` (JSONField list), `cross_site_configs` (JSONField list of
  `{site_no, offset_minutes, label, hidden_nos, date_start, date_end}`)

### `approval`
- **ApprovalRequest** — `user`, `site`, `approval_type` (stage_discharge/precipitation/
  groundwater), `period_start`, `period_end`, `response_data` (JSONField), `status`
  (draft/complete)

---

## Tools

### 1. Water Balance Plotter

Plot discharge time series for a primary site + related sites on a shared axis.
Saves configs as `FlowBalanceConfig`. Data: USGS IV API `00060`.

---

### 2. Rating Developer

Develop rating curves (stage vs. discharge) using the USGS current rating and field
measurements.

**Plotly trace index mapping** (critical for `Plotly.restyle`):
- Trace 0 — rating curve line (EXSA)
- Trace 1 — base control points (black diamonds)
- Traces 2–6 — field measurements by quality group (`QUALITY_ORDER` order):
  Excellent, Good, Fair, Poor, Unspecified
- Traces 7+ — cross-site transferred measurements (one trace per `cross_site_configs` entry)

**Cross-site measurements** — import field measurements from a secondary site and pair
each measurement's discharge with the primary site's interpolated GH at measurement time
+ configurable offset. Stored in `cross_site_configs`; default date range is last 6 months
(configurable via `date_start`/`date_end`); per-point visibility via `hidden_nos`.
Colors defined in `_CROSS_SITE_COLORS` in `views.py`. GH interpolation in
`_interpolate_gh()`.

**USGS data sources** (`rating_developer/usgs.py`):
- Rating: `https://waterdata.usgs.gov/nwisweb/get_ratings` (`file_type=exsa` / `base`)
- Field measurements: USGS OGC API (old NWIS endpoints deprecated 2025)
  - `https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items`
  - `https://api.waterdata.usgs.gov/ogcapi/v0/collections/channel-measurements/items`
  - Three fetches (discharge, gage height, measurement number) joined on `field_visit_id`

---

### 3. ALERT2 Dashboard

Tabular Novastar ALERT2 sensor data with transmit reliability tracking.
Site/group data, overview (1/7/30-day reliability), and summary views.
Superusers can manage point locators and transmit schedules.
Data: Novastar Point Data Viewer API (`alert2/novastar.py`).

---

### 4. Station Analysis

Guided authoring of USGS station analysis reports (stage/discharge, precipitation,
groundwater). Sections auto-saved; Export Prompt downloads a Copilot/GPT `.txt` file.

**Report types** defined in `analysis/report_types.py` — add one dict entry to add a type.
- Stage/Discharge: 18 sections
- Groundwater: 9 sections
- Precipitation: 9 sections

**Stage/discharge data panel:**
- Dual-axis Plotly chart (discharge + gage height), comparison sites, analysis period stats,
  water year stats table, field measurements table
- Water year always extended back to Oct 1 for extremes computation
- **Extremes for Water Year** auto-generated (read-only) — only for WYs whose Sep 30 falls
  within the analysis period. Format: "Maximum discharge, X ft³/s, Mmm. d, gage height,
  X.XX ft. Maximum gage height, X.XX ft, Mmm. d. Minimum daily discharge, X ft³/s, Mmm. d."
- Peak/GH dates formatted in gage local time using `tz_offset_min` from `fetch_iv()`

**Precipitation data panel:**
- Bar chart, summary stats, daily totals, data gaps (>2 hr), estimated data periods,
  comparison sites, tipping-bucket calibrations

**Prior Period Analysis** — paste previous period's text; included in prompt as:
1. Style/narrative reference (match tone, don't copy values)
2. Sections containing exactly `same as previous` → AI copies verbatim from prior text

**Prompt building:** `_build_copilot_prompt()` for Copilot/GPT export.
`fetch_iv()` returns `tz_offset_min` (Int32) column for local-time formatting.
`fetch_dv()` fetches official daily means (`statCd=00003`).

---

### 5. Approval Checklist

Standalone structured approval checklist (stage/discharge, precipitation, groundwater).
Questions: `yn` (radio + comment), `date` (picker + comment), `text` (textarea + color).
Conditional questions revealed by parent answer. Autosave (600ms debounce).
Report view: read-only formatted output with Copy Text + Export Word (`.docx`).
Question definitions in `approval/approval_types.py`; source: `examples/*_Approval.txt`.

---

### 6. ALERT2 Packet Parser

Decode raw ALERT2 IND packet strings. Stateless — no DB models.
Auto-detects format: AL22b binary frame, AL22a IND CSV, or bare hex MANT payload.
Single-packet decode and batch file upload views.
Accessed from the ALERT2 Dashboard index page (not home page).
Protocol references in `examples/Alert/`.

---

## Known Bugs

- **Field measurement join data loss** (`rating_developer/usgs.py` `fetch_measurements()`)
  — multiple records per `field_visit_id` keep only the last; earlier readings silently dropped.

- **Race condition on creation** — uniqueness checks on `AnalysisReport`, `FlowBalanceConfig`,
  `SiteRelationship` done in Python, not DB-enforced. Concurrent requests can create duplicates.
  Fix: `get_or_create` inside `transaction.atomic()`.

- **AI assist stream swallows errors** (`analysis/views.py` `_stream_ai_response`) — no
  error event sent to client on Anthropic API failure; UI hangs.

- **`update_dates` accepts unvalidated date strings** (`approval/views.py`,
  `analysis/views.py`) — invalid date causes unhandled 500.

---

## Open Questions / Pending

- [ ] Custom domain — point Railway to domain, add DKIM/DMARC in Brevo, update
  `CSRF_TRUSTED_ORIGINS` and `DEFAULT_FROM_EMAIL`
- [ ] Analysis data caching — USGS API called on every page load; add TTL cache +
  "Refresh Data" button
- [ ] Add test suite — priorities: USGS parsing helpers, ALERT2 decoder, extremes logic,
  auth flows
- [ ] Add Sentry error monitoring + structured logging
- [ ] Harden `SECRET_KEY` / `ALLOWED_HOSTS` for production
- [ ] Enable Railway PostgreSQL backups
- [ ] Migrate `unique_together` → `UniqueConstraint` on all models
- [ ] `reports` app — shared report saving across tools (not yet built)
