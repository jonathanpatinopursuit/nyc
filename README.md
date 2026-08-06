# Rat problem NYC

**Live site: https://nyc-sigma.vercel.app**

A data story: the Bronx racks up rodent-related housing violations at more
than five times the rate of the least-affected NYC borough. This site pulls
that comparison live from the city's own open data — a choropleth map, a
ranked bar chart, and the narrative behind the numbers.

## Where the data comes from

Everything on the page is fetched **live, on every page load**, from
[NYC Open Data](https://opendata.cityofnewyork.us/) (the city's public
Socrata data portal) — nothing is hardcoded or cached:

- **[HPD Housing Maintenance Code Violations](https://data.cityofnewyork.us/City-Government/Housing-Maintenance-Code-Violations/wvxf-dwi5)**
  (dataset `csn4-vhvf`) — every housing violation issued by NYC's Department
  of Housing Preservation & Development. The app queries violations whose
  description mentions "rodent," "rats," or "mice," issued from January 1,
  2020 onward, grouped by borough.
- **[Borough Boundaries](https://data.cityofnewyork.us/City-Government/Borough-Boundaries/gthc-hcne)**
  (dataset `gthc-hcne`) — the GeoJSON polygons behind the map. Geography
  doesn't change, so this is fetched once and baked into
  `public/nyc-boroughs.json` by `build_borough_map.py`, rather than re-fetched
  per page load.
- **2020 U.S. Census** borough population totals (hardcoded — these are
  official, static figures) — used to convert raw violation counts into a
  fair rate per 100,000 residents, so a borough isn't penalized or credited
  just for having more people.

## What's going on, technically

- `server.js` — an Express app. `/api/rodent-summary` queries the Socrata API
  server-side (grouped/aggregated, not raw rows) and returns violations per
  100k residents by borough. `/api/nyc-data` is a thin generic passthrough to
  the same dataset for ad-hoc queries.
- `public/index.html` — the page itself: fetches `/api/rodent-summary` and
  `/nyc-boroughs.json` client-side and renders the map, bar chart, data
  table, and narrative from live numbers (nothing is pre-rendered).
- `build_borough_map.py` — one-time script that fetches, simplifies, and
  projects the borough polygons into lightweight SVG path data.
- `rodent_mismanagement_analysis.py`, `rodent_violations_by_neighborhood.py`,
  `rodent_violations_per_capita.py` — standalone Python scripts used to
  explore the data and produce the CSVs checked into this repo (not used by
  the live site itself, which queries the API directly).

## Running locally

```bash
npm install
cp .env.example .env   # add your own NYC_OPEN_DATA_TOKEN (see below)
npm start              # http://localhost:3000
```

Get a free Socrata app token at
[data.cityofnewyork.us/profile/app_tokens](https://data.cityofnewyork.us/profile/app_tokens)
and put it in `.env` as `NYC_OPEN_DATA_TOKEN`. Without it, requests still
work but are rate-limited more aggressively.

## Deployment

Deployed on [Vercel](https://vercel.com), running `server.js` directly as
the server entrypoint. `NYC_OPEN_DATA_TOKEN` is set as a Vercel environment
variable (Production + Preview) rather than committed to the repo.
