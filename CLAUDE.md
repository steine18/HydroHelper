# USGS Hydrographer Toolbox — Project Notes for Claude

## Project Overview

A Django web application providing specialized tools for USGS hydrographers. The app
pulls data from the USGS Water Services REST API and a Novastar ALERT2 telemetry system,
with user accounts, saved reports, and persistent site relationship configurations.

---

## Tech Stack

- **Framework:** Django 6.0.3
- **Database:** PostgreSQL (user: `msteiner`, db: `hydrohelper`)
- **Frontend:** Bootstrap 5 (CDN)
- **Brand colour:** USGS green `#00843D` (dark variant `#006b31`)
- **Data manipulation:** Polars (time-series, time-of-travel shifting)
- **Visualization:** Plotly (interactive charts)
- **USGS data:** USGS Water Services REST API — no API key required
  - IV base URL: `https://waterservices.usgs.gov/nwis/iv/`
  - Site info URL: `https://waterservices.usgs.gov/nwis/site/`
  - Discharge parameter code: `00060` (cfs)
  - Gage height parameter code: `00065` (ft)
- **Novastar data:** Novastar Point Data Viewer API — documentation TBD

---

## Django App Structure

Apps currently built:
```
project/
└── water_balance/    # Flow Balance Plotter — built and functional
```

Apps planned (not yet created):
```
├── accounts/         # User registration, login, profiles
├── sites/            # USGS site models, site relationships, time-of-travel
├── rating_developer/ # Rating curve development tool
├── alert2/           # ALERT2 / Novastar dashboard tool
└── reports/          # Shared report saving/retrieval across tools
```

---

## Data Models (planned — not yet written)

### `sites` app

- **Site** — A USGS monitoring site (site number, name, coordinates, etc.)
- **SiteRelationship** — Links a primary site to a related site with a time-of-travel
  offset. Offset may eventually be flow-dependent rather than fixed.
- **NovaSite** — Maps a USGS site to one or more Novastar station IDs
- **NovaSensor** — Individual sensor addresses within a Novastar station
  (sensor type, address, units, label)

### `reports` app

- **Report** — Saved report belonging to a user; stores tool type, date range,
  site selections, offset values used, and any other tool-specific config

---

## Tools

### 1. Flow Balance Plotter — `water_balance` app

**URL:** `/flowbalance/` (site entry) → `/flowbalance/<site_number>/` (plot)

**Purpose:** Plot discharge time series for a primary site and one or more related
sites on a shared time axis to visualize water balance between locations.

**Built features:**
- Primary site entry page at `/flowbalance/`; redirects to `/flowbalance/<site_number>/`
- Site name fetched from USGS site service and displayed in the header
- Interactive Plotly chart — discharge (cfs) on a shared UTC time axis
- Adjustable date range (default: last 7 days)
- Error band on primary site (±N%, toggleable, default ±10%)
- Comparison sites with individual time-of-travel offsets (minutes)
- Per-comparison discharge offset (absolute cfs or percentage) for unknown gains/losses
- Fetch buffer — comparison sites fetched from `start - offset` so shifted series
  covers the full display range; plot x-axis pinned to primary date range
- Composite groups — assign multiple comparison sites the same group name to sum
  them into a single trace; each member has its own offset and +/− operation
- Sticky controls panel with internal scroll; Update Plot button always visible

**Planned features:**
- [ ] **Site map** — mini map beneath the plot showing primary and all comparison sites
  (including composite members). Coordinates from USGS site service endpoint.
- [ ] **Data table view** — toggleable table: timestamp, primary cfs, then per
  comparison site: shifted cfs, difference (cfs), % difference. Rows aligned to
  primary timestamps; use `join_asof` for misaligned intervals after shifting.

**Key files:**
- `water_balance/usgs.py` — USGS API client (`fetch_discharge`, `fetch_site_names`, `shift_time_of_travel`)
- `water_balance/views.py` — `flow_balance_index`, `flow_balance` views
- `water_balance/templates/water_balance/flow_balance_index.html`
- `water_balance/templates/water_balance/flow_balance.html`

**Data source:** USGS Water Services IV API, parameter `00060` (discharge)

---

### 2. Rating Developer — planned

**Purpose:** Develop rating curves (stage vs. discharge) at a site, supplemented by
field measurements and computed values from nearby upstream/downstream sites with
time-of-travel correction.

**Use Case A — Cross-site field measurements:**
A field measurement taken at site A at noon captures discharge directly. That discharge
value is paired with the gage height at site B one hour later, yielding a rating point
at site B without a physical measurement there.

**Use Case B — Computed value transfer:**
Continuous computed discharge from site A's existing rating is shifted forward by
time-of-travel and plotted against site B's gage height.

**Additional considerations:**
- Field measurements carry quality ratings (Excellent / Good / Fair / Poor)
- Visually distinguish native vs. cross-site transferred points on the rating curve
- Time-of-travel offset may eventually be flow-dependent
- Output: rating curve scatter plot with fitted curve, not a time series

**Data source:** USGS Water Services IV API (`00065`, `00060`) and USGS field measurements API

---

### 3. ALERT2 Dashboard — planned (blocked on Novastar API docs)

**Purpose:** Real-time tabular display of all sensor values from Novastar ALERT2
telemetry stations, mapped to their corresponding USGS sites.

**Key features:**
- Pulls data from the Novastar Point Data Viewer API (documentation TBD)
- Table: sensor type, current value, units, last reading timestamp, staleness indicator
- USGS-to-Novastar site mappings stored in the database
- Auto-refresh / polling behavior (interval TBD)

---

## Development Progress

- [x] Django project scaffolded with PostgreSQL
- [x] Bootstrap 5 + USGS green branding, shared base template
- [x] Home page (`/`) with tool cards
- [x] Flow Balance Plotter — core functionality complete
- [ ] User accounts / login
- [ ] `sites` app models
- [ ] Rating Developer
- [ ] ALERT2 Dashboard
- [ ] Shared `reports` app

---

## Open Questions / Decisions Pending

- [ ] Novastar API documentation — needed before `alert2` app development
- [ ] Flow-dependent time-of-travel — fixed offset for now, design for extensibility
- [ ] ALERT2 dashboard refresh rate / polling interval
- [ ] Who can manage USGS-to-Novastar mappings — admin only or any authenticated user?
- [ ] Deployment target (server, cloud, local network)
