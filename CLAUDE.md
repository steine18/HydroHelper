# USGS Hydrographer Toolbox — Project Notes for Claude

## Project Overview

A Django web application providing specialized tools for USGS hydrographers. The app
pulls data from the USGS Water Services REST API and a Novastar ALERT2 telemetry system,
with user accounts, saved reports, and persistent site relationship configurations.

---

## Tech Stack

- **Framework:** Django (chosen over Flask for built-in auth, ORM, and admin)
- **Auth:** `django-allauth` (v65.x) with Google OAuth (`allauth.socialaccount.providers.google`);
  custom user model in `accounts` app; mandatory email verification on registration;
  `email` field has `unique=True` (migration `0003_unique_email`)
- **Email:** Brevo SMTP (`smtp-relay.brevo.com`, port 587); login is the Brevo-generated
  SMTP login (`a6e7f5001@smtp-brevo.com`), NOT the account Gmail — set via `BREVO_SMTP_LOGIN`
  env var; password via `BREVO_SMTP_KEY`; `DEFAULT_FROM_EMAIL` env var;
  `EMAIL_BACKEND` env var overrides the backend (set to console backend locally if needed)
- **Static files:** WhiteNoise (`whitenoise.middleware.WhiteNoiseMiddleware`) serves
  static files in production; `STATIC_ROOT = BASE_DIR / 'staticfiles'`
- **Deployment:** Railway — PostgreSQL via `DATABASE_URL` env var; `Procfile` runs
  `migrate` + `collectstatic` on release, `gunicorn` on web; `.python-version` pins
  Python 3.12 for Nixpacks
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
├── accounts/         # Custom user model, registration, login (django-allauth + Google OAuth, Microsoft OAuth planned)
├── sites/            # USGS site models, site relationships, Novastar point locator mappings
├── water_balance/    # Water balance plotter tool (built)
├── alert2/           # ALERT2 / Novastar dashboard tool (built)
├── analysis/         # Station analysis report authoring tool (built)
├── rating_developer/ # Rating curve development tool (built)
├── approval/         # Approval checklist tool (built)
└── alert2_parser/    # ALERT2 IND packet decoder — single packet and batch file upload (built)
```

Apps planned but not yet created:

```
└── reports/          # Shared report saving/retrieval across tools (planned)
```

---

## Data Models

### `accounts` app (built)

- **User** — Extends `AbstractUser`. Added `email` field with `unique=True` and `tier`
  field (`basic` / `advanced`, default `basic`). `is_advanced` property returns `True`
  for advanced, staff, and superuser.
- **Tiers:**
  - `basic` — Flow Balance Plotter, ALERT2 Dashboard, Approval Checklist, ALERT2 Parser
  - `advanced` — all tools (adds Rating Developer and Station Analysis)
  - Staff/superuser — always advanced; can access `/accounts/admin-tools/users/` to
    toggle any non-superuser between basic and advanced
- **`accounts/decorators.py`** — `advanced_required` decorator; raises 403 for basic users
- **Views:** `register`, `account`, `add_site`, `manage_users`, `set_user_tier`
- **Admin:** `CustomUserAdmin` registered with tier column and filter

### `sites` app (built)

**Note:** The app's Django label is `usgs_sites` (set via `AppConfig.label`) to avoid
conflicting with `django.contrib.sites` which also uses the label `sites`. All FK
references use `'usgs_sites.Site'` and all migration dependencies use `('usgs_sites', ...)`.
Database tables are named `usgs_sites_site`, `usgs_sites_siterelationship`,
`usgs_sites_novapointlocator`.

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
- **StageQComparisonSite** — Links a comparison USGS site to a stage/discharge
  `AnalysisReport` for side-by-side discharge comparison. Unique per `(report, site)`.
  Related name: `stage_q_comparison_sites`.

### `rating_developer` app (built)

- **RatingConfig** — A saved rating configuration belonging to a user. Fields:
  `user` (FK), `site` (FK to `sites.Site`), `name`, `use_manual_rating` (bool),
  `manual_rating_text` (TextField), `hidden_measurement_nos` (JSONField, list of
  measurement number strings to exclude from the plot), `created_at`, `updated_at`.

### `approval` app (built)

- **ApprovalRequest** — A standalone approval checklist for a site and date range.
  Fields: `user` (FK), `site` (FK), `approval_type` (stage_discharge / precipitation /
  groundwater), `period_start`, `period_end`, `response_data` (JSONField — stores all
  answers keyed by question key), `status` (draft / complete), `created_at`, `updated_at`.
  Has a `completion_pct()` helper that counts answered questions across all types.

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
- **Water year extension** — `data_start` is always extended back to Oct 1 of the water
  year containing `period_start`, regardless of whether the period crosses a WY boundary.
  This ensures full WY data is available for extremes computation. The prior-analysis
  portion is shaded grey on the chart.
  Logic in `_water_year_start()` and `_stage_q_context()` in `analysis/views.py`.
- Displays a dual-axis Plotly time series chart (discharge blue/left, gage height orange/right)
- **Comparison sites** — add any number of USGS sites to compare discharge side-by-side;
  stored in `StageQComparisonSite`; comparison discharge traces are added to the chart
  in `_COMPARISON_COLORS` order; a side-by-side stats table shows peak, min instantaneous,
  and min daily mean for each site. Add/remove UI in the data panel header.
  URLs: `analysis_add_stage_q_comparison`, `analysis_delete_stage_q_comparison`.
  Helper: `_process_stage_q_site()` in `analysis/views.py`.
- **Analysis period stats** — two-column table (Discharge | Gage Height) showing peak,
  min instantaneous, and min daily mean filtered to `period_start`–`period_end` exactly.
  Labeled "Analysis Period: MM/DD/YYYY – MM/DD/YYYY". Minimum daily mean comes from the
  USGS DV API; falls back to IV-computed mean if DV returns no data.
- **Water year stats table** — compact table with one row per water year that intersects
  the analysis period (including partial WYs). Columns: Water Year, Peak Q (cfs) + date,
  Peak GH (ft) + date, Min Daily Q (cfs) + date. Uses `_water_years_intersecting()` in
  `analysis/views.py` (distinct from `_water_years_in_range()` which only returns
  closed-out WYs used for extremes sentences).
- **Field measurements table** — USGS field measurements from the analysis period fetched
  via `fetch_measurements()` from `rating_developer/usgs.py` (USGS OGC API). Columns:
  `#`, `Date`, `Stage (ft)`, `Discharge (cfs)`, `Quality` (color-coded using
  `QUALITY_COLORS` from `rating_developer/usgs.py`). Summary line shows count and
  discharge range (min–max cfs). Hidden if no measurements in the period. Errors from
  the API are silently ignored so a failed fetch doesn't break the page.
  Gage height values are always formatted to 2 decimal places throughout the panel.
- **Extremes for Water Year** section is auto-generated (read-only, no textarea) per water year.
  A sentence is only generated for water years that the analysis period **closes out** — i.e.,
  Sep 30 of that WY falls within the analysis period.
  - 9/25/25–3/1/26 → closes out WY25 only (Sep 30, 2025 is within range)
  - 10/2/25–3/1/26 → no extremes (Sep 30 of neither WY25 nor WY26 is within range)
  - 9/1/24–3/1/26 → closes out WY24 and WY25
  - Each entry rendered with a "Extremes for WYXX" header above the sentence.
  - Format: "Maximum discharge, X ft³/s, Mmm. d, gage height, X.XX ft. Maximum gage
    height, X.XX ft, Mmm. d. Minimum daily discharge, X ft³/s, Mmm. d." All three
    sentences are always included.
  - Extremes always use the full water year (Oct 1–Sep 30), never clipped to the
    analysis period start. `_water_years_in_range()` returns `wy_s` (Oct 1) as the
    range start, not `clip_start`.
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
- `*_Approval.txt` files — source of truth for approval checklist questions; used when
  building `approval/approval_types.py` but not loaded at runtime
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

### 5. Approval Checklist (built)

**Purpose:** Standalone structured approval checklist for stage/discharge, precipitation,
and groundwater station records. The reviewer fills out the checklist independently
(not linked to an existing AnalysisReport).

**Django app:** `approval/`

**Question types** (defined in `approval/approval_types.py`):
- `yn` — radio button group (Bootstrap btn-group) + comment textarea. Buttons are driven
  by an `options` list on each item (see below); always rendered with good options first.
- `date` — date picker + comment textarea
- `text` — large textarea + Green / Orange / Red color picker. The selected color is saved
  in `response_data[key].color` and applied to the text block in the report.

**`_yn` helper — `options` and `good_response`:**
- Every `yn` item carries an `options` list: `[{'value', 'label', 'good'}, ...]`
- `good_response='yes'` (default) → options order: Yes (green) · No (red) · N/A (gray)
- `good_response='no'` → options order: No (green) · Yes (red) · N/A (gray)
- `good_response='both'` → options order: Yes (green) · No (green) · N/A (gray)
- Custom `options=[ ]` list may be passed directly for non-standard buttons (e.g. q3_3
  in stage/discharge has No Ice · Yes · No · N/A with No Ice and Yes both green).
- N/A is always gray regardless of `good_response`.
- Good options always sort before bad options; N/A always last.
- In the report, `approval_report` view computes `ans_label` (display string) and
  `ans_class` (CSS class: `answer-yes`, `answer-no`, `answer-na`, `answer-blank`) for
  each `yn` response by looking up the answer value in the item's `options` list.

**Questions where `good_response='no'` (No is the good/green answer):**
- Stage/discharge 2.2 — "Are levels overdue?"
- Precipitation 2.2 — "Is a calibration overdue?"
- Precipitation 2.4 — "Did the calibration error exceed 5%?"
- Groundwater 3.2 — "Are levels or reference point inspections overdue?"

**Questions where `good_response='both'` (both Yes and No are acceptable/green) —**
these are all conditional gate questions where either answer is situationally fine:
- Stage/discharge 2.3, 2.4, 5.1, 5.2, 5.3
- Precipitation 2.3
- Groundwater 3.4, 3.5

**Text question color picker** — Green / Orange / Red radio buttons appear below each
`text`-type textarea. Selected color saved as `response_data[key].color`. Report applies:
- Green → `.answer-yes` (#198754)
- Orange → `.answer-orange` (#fd7e14)
- Red → `.answer-no` (#dc3545)
- No selection → unstyled (black)

**Conditional questions** — questions with `conditional_on` and `conditional_value` keys
are hidden by default and revealed when the referenced parent question is answered with
the required value (always `'yes'`). Nesting is supported (e.g., 5.2.1 depends on 5.2
which depends on 5.1). The frontend JS runs a stabilizing loop that repeats until no
visibility changes occur, handling arbitrary nesting depth.

**Approval types** (defined in `approval/approval_types.py`, source: `examples/*_Approval.txt`):
- `stage_discharge` — 16 sections, ~50 questions
- `precipitation` — 10 sections, ~20 questions
- `groundwater` — 11 sections, ~30 questions

**Views:**
- `index` — lists draft and completed approvals
- `new_approval` — form: site number, approval type, period start/end
- `approval_detail` — renders full checklist with autosave (600ms debounce, full
  `response_data` JSON posted on each change); sticky header (title, dates, buttons,
  progress bar stays visible while scrolling); "View Report" button opens report in new tab
- `autosave` — POST endpoint, saves entire `response_data` JSON blob
- `update_dates` — POST endpoint, saves edited `period_start`/`period_end` and redirects
  back to the checklist; date pickers are inline in the sticky header
- `toggle_complete` — flips status between draft/complete
- `delete_approval` — deletes with confirmation
- `approval_report` — read-only formatted report view; computes `ans_label`/`ans_class`
  from the item's `options` list so answer colors always reflect `good_response` correctly
- `export_docx` — generates and downloads a `.docx` file using `python-docx`; reuses the
  same visibility/conditional logic as `approval_report`; color-codes `yn` answers
  (green/red/gray) and `text` blocks (green/orange/red) using `RGBColor`

**Checklist detail** (`approval/approval_detail.html`):
- Sticky header contains title, approval type, inline date pickers (Save button posts to
  `update_dates`), status badge, Mark Complete / Reopen, View Report, and Delete buttons,
  plus a live progress bar
- Progress bar updates live in the browser on every change — JS mirrors `completion_pct()`
  logic (yn = has answer, date = has date, text = non-empty text) via a `QUESTIONS` array
  rendered into the page from the server-side items list

**Report view** (`approval/report.html`):
- Sticky header contains site title, approval type/period/status on the left, and Back to
  Checklist / Copy Text / Export Word buttons on the right
- Renders all answered questions; conditional questions whose parent was not "yes" are
  automatically omitted (visibility logic runs server-side in Python, mirroring the JS logic)
- `yn` answer color driven by `ans_class` computed in view — green if answer matches a
  good option, red if not, gray for N/A, light gray for unanswered
- `text` block color driven by `r.color` saved with the response
- Comment text appended inline after the answer in the same color
- Unanswered questions shown in light gray as "— not answered"
- **Copy Text** button — collects plain-text version of the report (section headers,
  question numbers, answers, comments) and copies to clipboard via `navigator.clipboard`
- **Export Word** button — links to `export_docx` view; downloads a `.docx` file

**URL namespace:** `approval/` (no app namespace, named URLs: `approval_index`,
`approval_new`, `approval_detail`, `approval_autosave`, `approval_toggle_complete`,
`approval_delete`, `approval_update_dates`, `approval_report`, `approval_export_docx`)

---

### 6. ALERT2 Packet Parser (built)

**Purpose:** Decode raw ALERT2 IND packet strings into human-readable form for
field verification and troubleshooting.

**Django app:** `alert2_parser/`

**URL prefix:** `alert2-parser/` (named URLs: `alert2_parser_decode`, `alert2_parser_batch`)

**Navigation:** Accessed from the ALERT2 Dashboard index page (`alert2/index.html`),
not from the home page. Two links appear below the "View All Sites Overview" button
under a "Packet Tools" label — one for single-packet decode and one for batch upload.

**Views:**
- `decode_view` — single packet decoder; accepts GET (`?packet=` prefill) and POST;
  auto-detects input format and renders hierarchical decoded output
- `batch_view` — file upload (one packet per line); renders a results table with
  valid/invalid badge, sensor summary, and a "Decode" button per row that posts the
  raw line directly to `decode_view`

**Input formats — auto-detected by `decode_packet()` in `alert2_parser/decoder.py`:**

1. **AL22b binary frame** — hex string whose bytes start with `414C323262` ("AL22b").
   This is the full binary IND API / Message API frame format (section 9.1 of the
   IND API spec). Structure after the `AL22b` prefix:
   - 1–2 byte extensible total-length field (bit 7 set → 2 bytes, 15-bit value)
   - Sequence of top-level TLVs decoded by `decode_binary_frame()`:
     - `0x00` ALERT2 Self-Report Protocol → value is the APDU, passed to `decode_apdu()`
     - `0x0A` / `0x0B` Set / Get Parameter → nested parameter TLVs decoded by
       `_decode_parameter_tlvs()`; parameter names from `IND_PARAMETER_NAMES` table
     - `0x10` ALERT2 Data Envelope → Message API output; nested via
       `_decode_data_envelope()` → `_decode_airlink_envelope()` + `_decode_mant_envelope()`
       (MANT payload decoded as APDU)
     - `0x02` Config & Control → recursively decoded nested IND API TLVs
     - `0x78/0x79/0x7A/0x7B/0x70` Save / Query / Reset / Load Configuration, GPS Cycle
       → no value, name shown only
   - Example from spec section 6.1.2:
     `414c3232621f0a0418021133001770020a0114000000682015100201081212032413220276`
     → Set Parameter (IND Address = 4403) + Self-Report (Tipping Bucket + General Sensor)

2. **IND CSV (AL22a)** — text lines starting with `AL2`; parsed by `decode_csv_lines()`.
   Record types: AirLink, MANT, Sensor, ALERT CCN. MANT port-0 payloads are
   automatically decoded as APDUs.

3. **Hex MANT payload** — bare hex string (colon / space / dash separated or compact);
   treated as a raw MANT Application PDU and passed directly to `decode_apdu()`.

**Application PDU (APDU) decoder — `decode_apdu()`:**
- Control byte: version (bits 0–1), timestamp present (bit 2), test flag (bit 3),
  APDU ID (bits 4–6; 7 = disabled), extensibility (bit 7)
- Optional 2-byte timestamp (seconds since last midnight or noon UTC)
- TLV sensor report records (extensible type + length fields):
  - Type 1 — General Sensor Report: `[sensor_id | F/L byte | value]` repeated
  - Type 2 — Tipping Bucket Rain Gage Report: sensor_id + F/L + accumulator + 1-byte time offsets
  - Type 3 — Multi-Sensor Report: flags byte drives which fixed fields are present
    (AT 2B signed 0.1°F, RH 1B, BP 2B, WS 1B, WD 2B, PW 1B, Stage 2B signed 0.01ft, BV 1B)

**Key lookup tables in `decoder.py`:**
- `SENSOR_NAMES` / `SENSOR_UNITS` — standard sensor IDs 1–11 + 255
- `MULTI_SENSOR_FIELDS` — bit definitions for Type 3 reports
- `IND_COMMAND_NAMES` — top-level TLV command types (0x00–0x8081)
- `IND_PARAMETER_NAMES` — parameter TLV types (0x18–0x8088) including Message API sub-TLVs
- `CLOCK_STATUS_LABELS`, `AIRLINK_ERROR_LABELS`, `MANT_ERROR_LABELS`, `PORT_LABELS`

**No database models** — the app is stateless; all decoding is done in memory in
`alert2_parser/decoder.py`. No migrations needed beyond the empty `migrations/__init__.py`.

**Protocol references** (in `examples/Alert/`):
- `Alert2_IND_API_Ver2.0_FINAL_2020-6.pdf` — IND API Specification v2.0 (June 2020);
  binary frame format in section 9.1, Message API TLVs in section 8.7, examples in sections 6–7
- `ALERT2_Description_102511.pdf` — Application layer protocol (control byte, TLV report
  types, sensor ID table, Multi-Sensor field table)

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
   precipitation data panel (gaps, estimated periods, calibrations, comparison sites),
   stage/discharge comparison sites, corrected extremes computation
8. ✅ Build `alert2_parser` app — single-packet decoder (AL22b binary frame, AL22a CSV,
   bare hex APDU) and batch file upload with valid/invalid assessment table
9. ✅ Build `approval` app — standalone approval checklist with three report types,
   conditional questions, autosave, formatted report view with copy-to-clipboard
10. ✅ Deploy to Railway — PostgreSQL, WhiteNoise static files, Procfile, gunicorn
11. ✅ User tier system — basic/advanced tiers, staff management UI, view gating
12. ✅ Password reset and email verification — Brevo SMTP, allauth templates, mandatory
    verification on registration; Brevo SMTP login is `a6e7f5001@smtp-brevo.com` (not
    account Gmail); allauth email confirmation template is `account/email_confirm.html`
    (note: NOT `confirm_email.html`)

---

## Performance Considerations

Known inefficiencies that are not urgent but worth addressing before production or at
scale:

- **Cross-request data re-fetching (`analysis/views.py`)** — The USGS API is called
  on every request with no caching. Loading a report page, clicking AI Assist, and
  exporting either prompt each independently re-fetch the same precipitation or
  stage/discharge data. The data-fetch logic for prompts is now consolidated into
  `_get_precip_data(report)` (refactored) and `_stage_q_context(report)`, but no
  TTL cache exists yet. Adding a short-lived server-side cache (e.g. Django's cache
  framework with a 5–15 min TTL keyed on `(site_no, param, start, end)`) plus a
  "Refresh Data" button would eliminate redundant external API round-trips.

- **`_precip_context` and `_get_precip_data` both fetch comparison sites** — When
  `report_detail` renders the page, `_precip_context` fetches comparison site data
  from both the DB and the USGS API. `_get_precip_data` (used by prompt builders) also
  queries the DB for comparison sites independently. These are separate requests so
  there is no duplication within a single request, but if a view ever needs both the
  chart context and the prompt data in the same request, there would be a double fetch.

- **Stage/discharge prompt builders call `_stage_q_context` without comparison sites**
  — `_build_all_sections_prompt` and `_build_copilot_prompt` call `_stage_q_context(report)`
  with no comparison sites, so comparison discharge data does not appear in the AI prompt
  even if comparison sites are configured. This is consistent but worth revisiting if
  richer prompt context is desired.

- **`fetch_measurements` in `rating_developer/usgs.py` fetches all historical measurements
  on every call** — Called from `analysis/views.py` on every stage/discharge report page
  load; no date filtering at the API level (filtering is done in Python). For sites with
  many decades of measurements this could be slow. Consider adding date range parameters
  to the OGC API call once the API supports them, or caching the result.

---

## Open Questions / Decisions Pending

- [ ] Flow-dependent time-of-travel — fixed offset for now, design for extensibility
- [ ] Deployment target (server, cloud, local network)
- [ ] Approval workflow — multi-user reviewer workflow not yet built (who can be a
      reviewer? notification mechanism?) — current app is single-user checklist only
- [ ] AI assist rate limiting — add per-user Django-level throttle before production
      (consider `django-ratelimit` on the `analysis_ai_assist_all` view)
- [ ] Anthropic API billing — separate from Claude.ai Pro; requires credits at
      console.anthropic.com; `ANTHROPIC_API_KEY` must be set in `.env` with no leading space
- [ ] Analysis data caching — precipitation and stage/discharge data is currently fetched
      live from the USGS API on every page load (no caching). Plan: add server-side caching
      with a TTL and an explicit "Refresh Data" button that busts the cache on demand
- [ ] Set up custom domain and complete email verification — purchase a domain (e.g. via
      Cloudflare Registrar or Namecheap), point it to Railway, add DKIM/DMARC DNS records
      in Brevo (Senders & IP → Domains), update CSRF_TRUSTED_ORIGINS and DEFAULT_FROM_EMAIL
      on Railway, then remove EMAIL_BACKEND override from .env to enable live email sending
- [ ] Style transactional emails — verification and password reset emails currently use
      allauth's plain-text defaults; replace with branded HTML templates in
      `templates/account/email/` (e.g. `email_confirmation_signup_message.html`)
- [ ] Replace Google OAuth with Microsoft OAuth — remove
      `allauth.socialaccount.providers.google` from INSTALLED_APPS and login template;
      add `allauth.socialaccount.providers.microsoft`, register app in Azure AD,
      set MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET env vars
