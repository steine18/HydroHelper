# USGS Hydrographer Toolbox — Project Notes for Claude

## Project Overview

Django web app for USGS hydrographers. Pulls data from the USGS Water Services REST API and
Novastar ALERT2 telemetry system; user accounts, saved configs, and site relationships.

---

## Tech Stack

- **Framework:** Django + PostgreSQL
- **Auth:** `django-allauth` (v65.x) with Microsoft OAuth; custom user model in `accounts`;
  mandatory email verification; `SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True`,
  `VERIFIED_EMAIL = True` (skips re-verification for Microsoft login)
- **Email:** Brevo SMTP (`smtp-relay.brevo.com:587`); login `a6e7f5001@smtp-brevo.com`
  (set via `BREVO_SMTP_LOGIN`); password via `BREVO_SMTP_KEY`; allauth confirmation
  template is `account/email_confirm.html` (NOT `confirm_email.html`)
- **Static files:** WhiteNoise in production; `STATIC_ROOT = BASE_DIR / 'staticfiles'`
- **Deployment:** Railway — `DATABASE_URL` env var; `Procfile` runs migrate + collectstatic
  on release, gunicorn on web; `.python-version` = 3.12
- **Data / Viz:** Polars (time-series), Plotly (interactive charts)
- **USGS API:** `https://waterservices.usgs.gov/nwis/iv/` — param `00060` (discharge, cfs),
  `00065` (gage height, ft), `00045` (precip, in)
- **Novastar:** Point Data Viewer API in `alert2/novastar.py`
- **AI assist:** Anthropic API (`claude-opus-4-5`), `ANTHROPIC_API_KEY` env var; SSE
  streaming; gated by `analysis.can_use_ai_assist` permission

---

## App Structure

```
accounts/         # Custom user model, tiers, MS OAuth
sites/            # USGS site cache, relationships, Novastar locators (label: usgs_sites)
water_balance/    # Water Balance Plotter
alert2/           # ALERT2 Dashboard
analysis/         # Station Analysis reports
rating_developer/ # Rating Developer
approval/         # Approval Checklist
alert2_parser/    # ALERT2 packet decoder
reports/          # (planned) shared report saving
```

**Important:** `sites` app uses Django label `usgs_sites` to avoid conflict with
`django.contrib.sites`. All FK references use `'usgs_sites.Site'`.

---

## Data Models

### `accounts`
- **User** — `AbstractUser` + `email` (unique) + `tier` (`basic`/`advanced`, default `basic`)
- Tiers: `basic` = Water Balance, ALERT2, Approval, Parser; `advanced` = all tools. Staff always advanced.
- `advanced_required` decorator in `accounts/decorators.py`

### `sites` (label: `usgs_sites`)
All FK references use `'usgs_sites.Site'`; tables named `usgs_sites_*`.
- **Site** — cached USGS site; auto-populated via `get_or_fetch()`; has `transmit_interval_hours`,
  `transmit_offset_minutes`
- **SiteRelationship** — upstream/downstream pair with `offset_minutes`; `fixed` and
  `flow_dependent` types (flow-dependent is a placeholder); per-user
- **LocatorGroup** — named group of point locators not tied to a USGS site (migration `0004_locatorgroup`)
- **NovaPointLocator** — maps a locator address to a `Site` or `LocatorGroup` (both FKs nullable);
  unique constraints on `('site', 'point_locator')` and `('group', 'point_locator')`

### `water_balance`
- **FlowBalanceConfig** — saved plot config; `comparison_sites` JSONField (list of dicts:
  `site_no`, `offset_minutes`, `discharge_offset`, `offset_type`, `operation`, `group`)

### `analysis`
- **AnalysisReport** — `section_data` JSON blob, `is_complete`, `prior_period_analysis`;
  unique `(user, site, period_start, period_end)`; permission `analysis.can_use_ai_assist`
- **PrecipCalibration** — tipping-bucket calibration; `error_pct()` = `(actual - desired) / desired * 100`
- **PrecipComparisonSite** — comparison USGS site for precip reports; unique `(report, site)`
- **StageQComparisonSite** — comparison site for stage/Q reports;
  related name `stage_q_comparison_sites`; unique `(report, site)`

### `rating_developer`
- **RatingConfig** — `user`, `site`, `name`, `use_manual_rating`, `manual_rating_text`,
  `hidden_measurement_nos` (JSONField list), `cross_site_configs` (JSONField list of
  `{site_no, offset_minutes, label, hidden_nos, date_start, date_end}`)

### `approval`
- **ApprovalRequest** — `approval_type` (stage_discharge / precipitation / groundwater),
  `response_data` JSONField, `status` (draft / complete)

---

## Tools

### 1. Water Balance Plotter
Plot discharge IV time series for a primary site + related sites with time-of-travel offsets.
Saves as `FlowBalanceConfig`. Data: USGS IV API `00060`.

### 2. Rating Developer
Stage vs. discharge rating curves using USGS current rating + historical field measurements.

**Plotly trace indices** (critical for `Plotly.restyle`):
- Trace 0 — rating curve line (EXSA)
- Trace 1 — base control points (black diamonds)
- Traces 2–6 — field measurements by quality group (`QUALITY_ORDER`): Excellent, Good, Fair, Poor, Unspecified
- Traces 7+ — cross-site transferred measurements (one trace per `cross_site_configs` entry)

**Cross-site measurements** — import field measurements from a secondary site and pair each
measurement's discharge with the primary site's interpolated GH at measurement time +
configurable offset. Stored in `cross_site_configs`; default date range is last 6 months
(configurable via `date_start`/`date_end`); per-point visibility via `hidden_nos`.
Colors in `_CROSS_SITE_COLORS`; GH interpolation in `_interpolate_gh()` in `views.py`.

**USGS data sources** (`rating_developer/usgs.py`):
- Rating: `https://waterdata.usgs.gov/nwisweb/get_ratings` (`file_type=exsa` / `base`)
- Field measurements: USGS OGC API (old NWIS endpoints deprecated 2025)
  - `https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items`
    (`parameter_code=00060` or `00065`)
  - `https://api.waterdata.usgs.gov/ogcapi/v0/collections/channel-measurements/items`
  - All three joined on `field_visit_id`

### 3. ALERT2 Dashboard
Tabular Novastar ALERT2 sensor data with transmit reliability tracking (1/7/30-day).
- Overview: normalised `all_rows` list with `detail_url`, `summary_url`, `display_name`,
  `display_subtitle` — template handles sites and groups uniformly
- Site + group data/summary views; superusers can add locators and set schedules
- Locator mappings in `sites.NovaPointLocator` (not in the `alert2` app)

### 4. Station Analysis
Guided authoring of USGS station analysis reports (stage/discharge, precipitation, groundwater).

**Report types** defined in `analysis/report_types.py` — add a new type = one dict entry, no
other changes.

**Key implementation details:**
- `prior_period_analysis` textarea: sections with text exactly `same as previous`
  (case-insensitive) tell the AI to copy that section verbatim from the prior text
- AI Assist (Claude streaming) buttons removed from UI; `ai_assist` / `ai_assist_all`
  endpoints still exist in `analysis/views.py` but are unlinked
- Prompt builders: `_build_copilot_prompt(report)` (Copilot/GPT `.txt` export);
  `_build_all_sections_prompt(report)` (legacy Claude, no longer exported to users)
- Shared helpers: `_daily_series(df_dv, df_iv)`, `_iv_series(df)` (converts UTC → local
  via per-row `tz_offset_min`)

**Stage/discharge data panel:**
- `data_start` always extended to Oct 1 of the water year containing `period_start` —
  `_water_year_start()` and `_stage_q_context()` in `analysis/views.py`
- Extremes auto-generated (read-only) only for water years the period **closes out**
  (Sep 30 of that WY falls within the analysis period); always use the full WY (Oct 1–Sep 30),
  never clipped to `period_start`
- Peak/GH dates formatted in gage local time using per-row `tz_offset_min`; DV dates are
  already local calendar dates and need no conversion
- Min daily discharge from USGS DV API; logic in `_water_years_in_range()` / `_stage_q_context()`
- Comparison sites: `_process_stage_q_site()`, URLs `analysis_add_stage_q_comparison` /
  `analysis_delete_stage_q_comparison`
- Field measurements via `fetch_measurements()` from `rating_developer/usgs.py`

**Precipitation data panel:**
- IV API `00045`; grouped bar chart + stats + daily totals
- Data gaps > 2 hours; estimated data (`e` qualifier); `PrecipCalibration` inline form
- Rain events: contiguous runs of days with precip > 0 in `_process_precip_site()`

**USGS IV API** — `fetch_iv()` in `water_balance/usgs.py` returns:
`site_no`, `datetime` (UTC), `value`, `unit`, `qualifiers` (comma-joined), `tz_offset_min`
(Int32 — UTC offset in minutes, e.g. `-420` for `-07:00`).

**USGS DV API** — `fetch_dv()` in `water_balance/usgs.py`; `statCd=00003`; returns
`site_no`, `date` (local calendar date), `value`, `unit`.

### 5. Approval Checklist
Standalone approval checklist (stage/discharge, precipitation, groundwater), not linked to
an AnalysisReport.

**Question types:** `yn` (radio btn-group + comment), `date` (picker + comment),
`text` (textarea + Green/Orange/Red color picker stored in `response_data[key].color`)

**`_yn` helper — `good_response`:**
- `'yes'` (default) → Yes(green) · No(red) · N/A(gray)
- `'no'` → No(green) · Yes(red) · N/A(gray) — e.g. "Are levels overdue?"
- `'both'` → Yes(green) · No(green) · N/A(gray) — gate questions where either is fine
- Custom `options=[]` list for non-standard buttons (e.g. S/D q3_3 has "No Ice" as green)
- `approval_report` view computes `ans_label` + `ans_class` by looking up the answer in
  the item's `options` list

**Conditional questions:** `conditional_on` + `conditional_value='yes'`; hidden by default,
revealed by JS stabilizing loop (supports arbitrary nesting depth).

**Views:** `approval_detail` (autosave, 600ms debounce), `approval_report` (read-only,
server-side visibility mirrors JS logic), `export_docx` (python-docx, same visibility logic).
URL names prefixed `approval_`.

### 6. ALERT2 Packet Parser
Stateless decoder for ALERT2 IND packets (`alert2_parser/decoder.py`). No DB models.
Accessed from the ALERT2 Dashboard index, not the home page.

**Input formats** (auto-detected by `decode_packet()`):
1. **AL22b binary** — hex starting with `414C323262`; top-level TLVs decoded by `decode_binary_frame()`
2. **IND CSV (AL22a)** — lines starting with `AL2`; `decode_csv_lines()`; MANT port-0 → APDU
3. **Bare hex APDU** — passed directly to `decode_apdu()`

**APDU structure:** control byte → optional 2-byte timestamp → TLV records
(Type 1 general sensor, Type 2 tipping bucket, Type 3 multi-sensor).

Protocol PDFs in `examples/Alert/`.

---

## Known Bugs

- **Silent data loss in `fetch_measurements()`** (`rating_developer/usgs.py`) — join on
  `field_visit_id` keeps only the last record per visit; silently discards earlier readings.

- **Race condition on creation** — `unique_together` checked in Python, not enforced at DB.
  Fix: `get_or_create` inside `transaction.atomic()` + `UniqueConstraint`.

- **`update_dates` accepts unvalidated date strings** (`approval/views.py`,
  `analysis/views.py`) — invalid date → unhandled 500. Fix: `datetime.strptime` + return 400.

---

## Performance Considerations

- **No USGS data caching** — every request re-fetches. Plan: Django cache with 5–15 min TTL
  keyed on `(site_no, param, start, end)` + "Refresh Data" button.
- **`fetch_measurements()` fetches all historical data** — no API-level date filter; slow for
  sites with decades of measurements.
- **No memory cap on large requests** — multi-year minute-level data can consume several GB.
- **No background task queue** — long USGS fetches and AI calls block the request thread.

---

## Open Questions / Decisions Pending

- [ ] Flow-dependent time-of-travel offset (placeholder only)
- [ ] Approval workflow — multi-user reviewer, notification mechanism
- [ ] AI assist rate limiting — `django-ratelimit` on `analysis_ai_assist_all`
- [ ] Analysis data caching — TTL cache + "Refresh Data" button
- [ ] Custom domain — buy domain, point to Railway, DKIM/DMARC in Brevo, update
      `CSRF_TRUSTED_ORIGINS` and `DEFAULT_FROM_EMAIL`
- [ ] Style transactional emails — branded HTML in `templates/account/email/`
- [ ] Sentry error monitoring — `sentry-sdk[django]`, `SENTRY_DSN`, `/health/` view
- [ ] Structured logging — add `LOGGING` config for 500s, USGS/Anthropic failures, auth events
- [ ] Harden `SECRET_KEY`/`ALLOWED_HOSTS` — remove insecure defaults; raise
      `ImproperlyConfigured` if `SECRET_KEY` unset when `DEBUG=False`
- [ ] Enable Railway PostgreSQL point-in-time recovery
- [ ] Move Anthropic model to env var — `ANTHROPIC_MODEL` (currently hardcoded `claude-opus-4-5`)
- [ ] Migrate `unique_together` → `UniqueConstraint` on `AnalysisReport`,
      `FlowBalanceConfig`, `SiteRelationship`, `PrecipComparisonSite`, `StageQComparisonSite`
- [ ] Add test suite — `pytest-django`; priorities: USGS helpers, ALERT2 decoder, extremes
      logic, auth flows
