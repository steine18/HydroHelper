# USGS Hydrographer Toolbox — Project Notes for Claude

## Project Overview

A Django web application providing specialized tools for USGS hydrographers. The app
pulls data from the USGS Water Services REST API and a Novastar ALERT2 telemetry system,
with user accounts, saved reports, and persistent site relationship configurations.

---

## Tech Stack

- **Framework:** Django (chosen over Flask for built-in auth, ORM, and admin)
- **Auth:** `django-allauth` with Google OAuth (`allauth.socialaccount.providers.google`);
  custom user model in `accounts` app
- **Database:** PostgreSQL
- **Data manipulation:** Polars (time-series, time-of-travel shifting)
- **Visualization:** Plotly (interactive charts)
- **USGS data:** USGS Water Services REST API — no API key required
  - Base URL: `https://waterservices.usgs.gov/nwis/iv/`
  - Discharge parameter code: `00060` (cfs)
  - Gage height parameter code: `00065` (ft)
  - Precipitation parameter code: `00045` (inches, incremental per recording interval)
- **Novastar data:** Novastar Point Data Viewer API — implemented in `alert2/novastar.py`
- **AI assist:** Anthropic API (`claude-opus-4-5`) via the `anthropic` Python package
  - Single server-side API key (`ANTHROPIC_API_KEY` environment variable)
  - Responses streamed to the browser via Server-Sent Events
  - Access gated by the `analysis.can_use_ai_assist` Django permission

---

## Django App Structure

Apps that currently exist on disk:

```
project/
├── accounts/         # Custom user model, registration, login (django-allauth + Google OAuth)
├── sites/            # USGS site models, site relationships, Novastar point locator mappings
├── water_balance/    # Water balance plotter tool (built)
├── alert2/           # ALERT2 / Novastar dashboard tool (built)
├── analysis/         # Station analysis report authoring tool (built)
└── rating_developer/ # Rating curve development tool (built)
```

Apps planned but not yet created:

```
├── reports/          # Shared report saving/retrieval across tools (planned)
├── alert2_parser/    # ALERT2 IND packet decoder — single packet and batch file upload (planned)
└── approval/         # Report review and approval workflow (planned)
```

---

## Data Models

### `sites` app (built)

- **Site** — A cached USGS monitoring site (site number, name, coordinates, HUC).
  Auto-populated from the USGS site service API on first use via `get_or_fetch()`.
  Also stores ALERT2 transmit schedule fields:
  - `transmit_interval_hours` — scheduled ALERT2 transmit interval (e.g. 1, 4, 8 hours)
  - `transmit_offset_minutes` — minutes offset within each interval
- **SiteRelationship** — Links an upstream site to a downstream site with a time-of-travel
  offset (`offset_minutes`). Supports `fixed` and `flow_dependent` offset types
  (flow-dependent is a future placeholder). Per-user (`created_by` FK).
- **NovaPointLocator** — Maps a USGS site to a single Novastar point locator address.
  A site may have multiple locators (one per sensor/parameter). Fields: `point_locator`,
  `parameter_type`, `label`.

### `water_balance` app (built)

- **FlowBalanceConfig** — A saved flow balance plot configuration belonging to a user.
  Stores primary site FK, name, date range, error band settings, and a JSON list of
  comparison site configs (`comparison_sites`: list of dicts with `site_no`,
  `offset_minutes`, `discharge_offset`, `offset_type`, `operation`, `group`).

### `reports` app (planned — not yet built)

- **Report** — Saved report belonging to a user; stores tool type, date range,
  site selections, offset values used, and any other tool-specific config

### `analysis` app (built)

- **AnalysisReport** — A station analysis report for a specific site and date range.
  Stores report type, period, and per-section text as a JSON blob (`section_data`).
  Has a `completion_pct()` helper, a `saved_to_reports` flag, and an `is_complete`
  boolean flag (default False) for marking a report as finished.
  Unique constraint on `(user, site, period_start, period_end)` — duplicate reports
  for the same user/site/dates are blocked at the DB level; the new report form and
  edit-dates view redirect to the existing report instead of raising an error.
  Custom permission: `analysis.can_use_ai_assist`.
- **PrecipCalibration** — A tipping-bucket calibration record linked to an
  `AnalysisReport`. Fields: `date`, `desired_tips` (FloatField), `actual_tips` (FloatField).
  `error_pct()` computed as `(actual - desired) / desired * 100` (negative = under-reading).
- **PrecipComparisonSite** — Links a comparison USGS site to a precipitation
  `AnalysisReport` for side-by-side data display. Unique per `(report, site)`.

### `rating_developer` app (built)

- **RatingConfig** — A saved rating configuration belonging to a user. Fields:
  `user` (FK), `site` (FK to `sites.Site`), `name`, `use_manual_rating` (bool),
  `manual_rating_text` (TextField), `hidden_measurement_nos` (JSONField, list of
  measurement number strings to exclude from the plot), `created_at`, `updated_at`.

### `approval` app (planned — not yet built)

- **ApprovalRequest** — Links an `AnalysisReport` to a submitter and optional reviewer.
  Status machine: `pending → approved / rejected / revised / withdrawn`.
- **ApprovalComment** — Comments on an approval request. Can be general or anchored
  to a specific report section via `section_key`, enabling future inline display.

---

## Tools

### 1. Water Balance Plotter (built)

**Purpose:** Plot discharge time series for a primary site and one or more related
sites on a shared time axis to visualize water balance between locations.

**Key features:**
- Select a primary USGS site (e.g., `09419800`)
- Attach one or more related sites (e.g., `09419700`)
- Adjust time-of-travel offset per related site (shift time series forward/backward)
- Interactive Plotly chart with all sites on a shared axis
- Save plot configurations (`FlowBalanceConfig`) for reuse

**Data source:** USGS Water Services IV API, parameter `00060` (discharge)

---

### 2. Rating Developer (built)

**Purpose:** Develop rating curves (stage vs. discharge) at a site using the USGS
current rating and historical field measurements.

**Key features:**
- Enter a USGS site number to create a saved `RatingConfig`
- **Rating source** — pull the current rating from the USGS API or enter manually
  (tab/comma/space-separated stage–discharge pairs)
- **Rating plot** — interactive Plotly chart (log x-axis by default, toggleable to
  linear) showing:
  - Trace 0: Full EXSA interpolated rating as a smooth line (no markers)
  - Trace 1: Base control points as black diamond markers
  - Traces 2–6: Historical field measurements color-coded by quality group
    (Excellent / Good / Fair / Poor / Unspecified)
- **Rating points table** — displayed beside the chart; shows only the base control
  points; editable (add/delete rows, save back as manual rating text)
- **Field measurements table** — all historical measurements with columns:
  `#`, `Date`, `Stage (ft)`, `Discharge (cfs)`, `Quality`
  - Per-row checkbox toggles visibility on the plot (persisted to `hidden_measurement_nos`)
  - Header checkbox checks/unchecks all currently visible (filtered) rows at once
  - Client-side date range filter (hides/shows rows without affecting the plot)
  - Sortable columns — click any header to sort asc/desc; Quality sorts by severity
    (Excellent → Good → Fair → Poor → Unspecified)

**Plotly trace index mapping** (important for `Plotly.restyle` calls):
- Trace 0 — rating curve line
- Trace 1 — control points
- Traces 2–6 — quality groups in `QUALITY_ORDER` order

**USGS data sources** (`rating_developer/usgs.py`):
- Rating table: `https://waterdata.usgs.gov/nwisweb/get_ratings`
  - `file_type=exsa` — full shift-adjusted expanded table (curve line)
  - `file_type=base` — base control points only (table + markers)
- Field measurements: **USGS OGC API** (old NWIS endpoints are permanently
  redirected/deprecated as of 2025)
  - Discharge: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items`
    with `parameter_code=00060`
  - Gage height: same endpoint with `parameter_code=00065`
  - Measurement number: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/channel-measurements/items`
  - All three fetched independently and joined on `field_visit_id`

**Planned additions (not yet built):**
- Use Case A — Cross-site field measurements: pair a discharge measurement from site A
  with the gage height at site B (time-of-travel shifted) to produce a transferred
  rating point
- Use Case B — Computed value transfer: shift site A's continuous discharge forward
  by time-of-travel and plot against site B's gage height

---

### 3. ALERT2 Dashboard (built)

**Purpose:** Tabular display of Novastar ALERT2 sensor data mapped to USGS sites,
with transmit reliability tracking.

**Key features:**
- Site lookup by USGS site number; point locators fetched from `NovaPointLocator` records
- **Site data view** — table of all readings for a date range, one column per sensor
- **Overview view** — all configured sites with 1-day / 7-day / 30-day transmit
  reliability summaries
- **Summary view** — per-site daily transmit stats for a configurable date range;
  superusers can set the transmit schedule (`interval_hours`, `offset_minutes`) here
- Superusers can add new point locators directly from the site data UI
- Point locator mappings stored in `sites.NovaPointLocator` (not in `alert2` app)

**Data source:** Novastar Point Data Viewer API (`alert2/novastar.py`)

---

### 4. Station Analysis (built)

**Purpose:** Guided authoring of formal USGS station analysis reports
(precipitation, stage/discharge, or groundwater) for a specified site and date range.

**Key features:**
- Select site number, report type, and analysis period to create a new report;
  duplicate (same user + site + dates) redirects to the existing report
- Report rendered as a series of sections, each with official guidance text
- User fills sections manually via textarea; changes auto-saved to the database
- **Mark Complete / Reopen** — toggles `is_complete`; completed reports move to a
  separate "Completed" section on the index page with a green badge
- **Delete** — deletes the report with a confirmation dialog
- **Edit dates** — inline date pickers in the report header; conflicts redirect to
  the existing report rather than saving
- **AI Assist** — single button that generates or improves all sections in one pass,
  streamed in real time directly into each section's textarea with autosave per section.
  Controlled by the `analysis.can_use_ai_assist` Django permission (see below).
- **Export Prompt (Claude)** — downloads the AI prompt as a `.txt` file optimised for
  Claude.ai; uses `[SECTION:key]` markers and ALL-CAPS data blocks.
- **Export Prompt (Copilot)** — downloads a GPT-optimised prompt; uses markdown `##`
  headings, suppresses preamble/closing remarks, no routing markers.
- Progress indicator shows % of sections with non-empty text

**Report types** are defined in `analysis/report_types.py` — adding a new type means
adding one dict entry there, no other changes needed. Current types:
- **Stage/Discharge** — 18 sections derived from `examples/Stage_Q/Stage_Q_Analysis.txt`:
  Gage Height Record, Datum, Backup Data, Ice Affected, Edits, Gage-Height Corrections,
  Other Corrections, Peak Stage, Stage-Discharge Relation, Discharge Measurements and
  Control Conditions, Shift Curves, Application of Shift Curves, Computed Discharge,
  Estimates, Hydrographic Comparison, Peak Streamflow, Extremes for Water Year, Comments
- **Groundwater** — 9 sections derived from `examples/GW/GW_Analysis.txt`:
  Extreme for Period of Analysis/Period of Record, Water-Level Fluctuations/Trends,
  Missing Data, Measurements, Datum Corrections, Water-Level Corrections,
  Hydrographic Comparison, Comments, Special Notes
- **Precipitation** — 9 sections matching the official USGS template (Precipitation
  Record, Backup Data, Missing Data, Edits, Corrections, Estimates, Hyetographic
  Comparison, Calibrations, Comments)

**Stage/discharge report data panel** (shown above sections for stage/discharge reports):
- Fetches discharge (00060) and gage height (00065) IV data, plus official daily values (DV,
  `statCd=00003`) for both parameters via `fetch_dv()` in `water_balance/usgs.py`.
- **Water year extension** — if the analysis period crosses Oct 1, the IV/DV fetch is extended
  back to Oct 1 of the water year containing `period_start`. Example: 7/1/25–12/1/25
  fetches from 10/1/24. The prior-WY portion is shaded grey on the chart.
  Logic in `_water_year_start()` and `_stage_q_context()` in `analysis/views.py`.
- Displays a dual-axis Plotly time series chart (discharge blue/left, gage height orange/right)
- Stats table: peak, minimum instantaneous, and minimum daily mean for both parameters.
  Minimum daily mean values come from the USGS DV API (official approved daily means), not
  computed by averaging IV data. Falls back to IV-computed mean if DV returns no data.
- **Extremes for Water Year** section is auto-generated (read-only, no textarea) per water year.
  A sentence is only generated for water years that the analysis period **closes out** — i.e.,
  Sep 30 of that WY falls within the analysis period.
  - 9/25/25–3/1/26 → closes out WY25 only (Sep 30, 2025 is within range)
  - 10/2/25–3/1/26 → no extremes (Sep 30 of neither WY25 nor WY26 is within range)
  - 9/1/24–3/1/26 → closes out WY24 and WY25
  - Each entry rendered with a "Extremes for WYXX" header above the sentence.
  - Format: "Maximum discharge, X ft³/s, Mmm. d, gage height, X.XX ft. Minimum daily
    discharge, X ft³/s, Mmm. d. Peak gage height, X.XX ft, Mmm. d." (third sentence only
    if peak gage height date differs from peak discharge date).
  - Minimum daily discharge comes from the USGS DV API (official daily mean).
  - Peak/gage-height dates are formatted in the **gage's local time zone**. The IV API
    returns timestamps with the local UTC offset embedded (e.g. `-07:00`). `fetch_iv()`
    captures this as a `tz_offset_min` (Int32) column on every record via
    `_parse_tz_offset_min()` in `water_balance/usgs.py`. The extremes computation applies
    the per-row offset (`peak_dt_utc + timedelta(minutes=tz_offset_min)`) before formatting,
    so DST transitions mid-period are handled correctly. DV dates are already local calendar
    dates by USGS convention and need no conversion.
  - Logic in `_water_years_in_range()` and `_stage_q_context()` in `analysis/views.py`.
  - Prompt builders instruct the AI to use only the generated text verbatim, or leave the
    section blank if no extremes were generated.
- No calibrations panel (precipitation only)

**Precipitation report data panel** (shown above sections for precipitation reports):
- Fetches USGS IV API parameter `00045` (precipitation, inches) for the analysis period
- Displays a grouped bar chart, summary stats table, and daily totals table
- **Comparison sites** — add any number of USGS sites to compare side-by-side;
  stored in `PrecipComparisonSite`; chart and stats table update to include all sites
- **Data gaps** — periods > 2 hours with no readings, listed with start time and duration
- **Estimated data** — contiguous periods of records carrying the `e` qualifier,
  count shown in metrics table
- **Calibrations** — tipping-bucket calibration records stored in `PrecipCalibration`;
  add via inline form (date, desired tips, actual tips as floats); error % auto-calculated

**Example / guidance files** (`examples/` directory):
- `examples/precip/Precip Example.txt` — filled-in example report; embedded in prompts
  as tone/style reference (labelled "EXAMPLE REPORT")
- `examples/Stage_Q/Stage_Q_Analysis.txt` — official section guidance; embedded in prompts
  as section guidance (labelled "SECTION GUIDANCE")
- `examples/GW/GW_Analysis.txt` — same for groundwater
- `*_Approval.txt` files exist but are not used yet (reserved for approval workflow)
- Loaded at runtime by `_load_example(report_type)` in `analysis/views.py` — editing the
  files updates the prompts without any code changes

**AI Assist prompt context:**
- All section guidance and existing section text
- Observed data block (report-type specific — see data panels above)
- Example/guidance file for the report type
- Explicit rules: only use provided data values, use `[placeholders]` for missing info,
  dates as mm/dd/yyyy, no section headings in output
- Precipitation-specific rule: Precipitation Record must include event summary sentence
  ("Total rain was X.XX inches with Y events ranging from A.AA to Z.ZZ in.")
- Rain events computed in `_process_precip_site()` as contiguous runs of days with precip > 0
- The same data and rules are included in both exported prompt formats

**Prompt building** — `_build_all_sections_prompt(report)` in `analysis/views.py` is the
single source of truth for the Claude AI prompt. `_build_copilot_prompt(report)` mirrors
it with markdown formatting for GPT-based models. Both `ai_assist_all` and `export_prompt`
call the appropriate builder.

**USGS IV API** — `fetch_iv()` in `water_balance/usgs.py` returns a DataFrame with columns:
`site_no`, `datetime` (UTC), `value`, `unit`, `qualifiers` (comma-joined, e.g. `"A,e"`),
and `tz_offset_min` (Int32 — the UTC offset in minutes extracted from each record's raw
datetime string before UTC conversion, e.g. `-420` for `-07:00`).

**USGS DV API** — `fetch_dv()` in `water_balance/usgs.py` fetches official daily mean values
(`statCd=00003`) from `https://waterservices.usgs.gov/nwis/dv/`. Returns columns:
`site_no`, `date` (Date), `value`, `unit`. Date is the local calendar date as returned by USGS.

**AI Assist permission:**
- Custom Django permission: `analysis.can_use_ai_assist`
- Defined in `AnalysisReport.Meta.permissions`
- Assigned per-user or via Groups in the Django admin
- Users without the permission do not see the AI Assist button (template-gated)
  and receive a 403 if they call the endpoint directly (view-gated)
- All AI calls use the server-side `ANTHROPIC_API_KEY` environment variable;
  users never interact with the Anthropic API directly

---

### 5. ALERT2 Packet Parser (planned)

**Purpose:** Decode raw ALERT2 IND packet strings into human-readable form for
field verification and troubleshooting.

**Planned features — Phase 1 (single packet):**
- Text input accepts a raw ALERT2 IND packet string
- Decodes and displays all fields in a readable layout

**Planned features — Phase 2 (batch file upload):**
- Upload a file containing one packet string per row
- Each packet assessed as **valid** or **invalid** (with reason)
- Results displayed as a table; clicking a row navigates to a detail view
  showing the fully decoded packet fields

**Django app:** `alert2_parser` (new app, not yet created)

---

### 6. Report Approval (planned)

**Purpose:** Structured review and approval workflow for completed station analysis
reports. A hydrographer submits a report; a reviewer approves, rejects, or requests
revisions.

**Planned workflow:**
1. Author submits completed `AnalysisReport` → creates an `ApprovalRequest`
2. Reviewer is assigned (or self-selects)
3. Reviewer reads report sections, leaves general or section-specific comments
4. Reviewer approves or rejects with required comment
5. On rejection, author revises and resubmits

**Key design decision pending:** Who can be a reviewer — any authenticated user,
staff only, or a specific Django Group?

---

## Development Approach

1. ✅ Stand up Django project with PostgreSQL and the `accounts` app — login/logout/
   registration working with `django-allauth` and Google OAuth
2. ✅ Build `sites` app models — shared across all tools
3. ✅ Build Water Balance Plotter (`water_balance` app)
4. ✅ Build ALERT2 Dashboard (`alert2` app)
5. ✅ Build Rating Developer (`rating_developer` app)
6. Build shared `reports` app for saving/retrieving configurations
7. ✅ Build `analysis` app — station analysis report authoring with AI assist,
   precipitation data panel (gaps, estimated periods, calibrations, comparison sites)
8. Build `alert2_parser` app — single-packet decoder, then batch file upload with
   valid/invalid assessment table and per-packet detail view
9. Build `approval` app — workflow logic, forms, and review UI

---

## Open Questions / Decisions Pending

- [ ] Flow-dependent time-of-travel — fixed offset for now, design for extensibility
- [ ] Deployment target (server, cloud, local network)
- [ ] Approval workflow — who is eligible to be a reviewer?
- [ ] Approval workflow — notification mechanism (email, in-app, or both)?
- [ ] AI assist rate limiting — add per-user Django-level throttle before production
      (consider `django-ratelimit` on the `analysis_ai_assist_all` view)
- [ ] Anthropic API billing — separate from Claude.ai Pro; requires credits at
      console.anthropic.com; `ANTHROPIC_API_KEY` must be set in `.env` with no leading space
- [ ] Analysis data caching — precipitation and stage/discharge data is currently fetched
      live from the USGS API on every page load (no caching). Plan: add server-side caching
      with a TTL and an explicit "Refresh Data" button that busts the cache on demand
