import 'dotenv/config';
import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';

const SODA_URL = 'https://data.cityofnewyork.us/resource/csn4-vhvf.json';
const { NYC_API_KEY_NAME, NYC_API_KEY_ID, NYC_OPEN_DATA_TOKEN } = process.env;
const __dirname = path.dirname(fileURLToPath(import.meta.url));

// 2020 Census borough populations
const BORO_POPULATION = {
  BRONX: 1_472_654,
  BROOKLYN: 2_736_074,
  MANHATTAN: 1_694_251,
  QUEENS: 2_405_464,
  'STATEN ISLAND': 495_747,
};

const DATE_WHERE =
  "novissueddate >= '2020-01-01T00:00:00' AND novissueddate < '2027-01-01T00:00:00'";
const PEST_WHERE =
  "(upper(novdescription) like '%RODENT%' OR upper(novdescription) like '%RATS%' OR upper(novdescription) like '%MICE%')";

function sodaHeaders() {
  const headers = { Accept: 'application/json' };
  if (NYC_OPEN_DATA_TOKEN) {
    headers['X-App-Token'] = NYC_OPEN_DATA_TOKEN;
  }
  return headers;
}

async function sodaGroupCount(select, where, group) {
  const url = new URL(SODA_URL);
  url.searchParams.set('$select', select);
  url.searchParams.set('$where', where);
  url.searchParams.set('$group', group);
  url.searchParams.set('$limit', '50000');

  const response = await fetch(url, { headers: sodaHeaders() });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`SODA request failed (${response.status}): ${text}`);
  }
  return response.json();
}

// Socrata has no index on novdescription, so PEST_WHERE's `like '%RODENT%'`
// has to text-scan the whole violations table before it can group/aggregate
// — about 30s per query. That's slow enough to time out a page load (and did:
// /api/rodent-by-zip hanging for 30s+ on every request was silently breaking
// the "look up your zip" feature, since the client gives up and shows a
// generic error). Each of the three routes below hits a distinct query shape
// (grouped by boro, by boro+closed, by zip), so each gets its own cache entry.
const RESPONSE_CACHE_TTL_MS = 30 * 60 * 1000;
const responseCache = new Map(); // key -> { data, fetchedAt }
const responseCacheInFlight = new Map(); // key -> in-flight promise, dedupes concurrent cold requests

async function cachedFetch(key, fn) {
  const hit = responseCache.get(key);
  if (hit && Date.now() - hit.fetchedAt < RESPONSE_CACHE_TTL_MS) {
    return hit;
  }
  if (!responseCacheInFlight.has(key)) {
    const promise = fn()
      .then((data) => {
        const entry = { data, fetchedAt: Date.now() };
        responseCache.set(key, entry);
        return entry;
      })
      .finally(() => {
        responseCacheInFlight.delete(key);
      });
    responseCacheInFlight.set(key, promise);
  }
  return responseCacheInFlight.get(key);
}

const app = express();

// Live pull from NYC Open Data (HPD Housing Maintenance Code Violations):
// rodent/rat/mice-related violations per borough since 2020, normalized per 100k residents.
app.get('/api/rodent-summary', async (req, res) => {
  try {
    const { data: summary, fetchedAt } = await cachedFetch('rodent-summary', async () => {
      const pestRows = await sodaGroupCount(
        'boro, count(*) as pest_count',
        `${DATE_WHERE} AND ${PEST_WHERE}`,
        'boro'
      );

      return pestRows
        .map((row) => {
          const boro = (row.boro || '').toUpperCase();
          const population = BORO_POPULATION[boro];
          if (!population) return null;
          const pestCount = parseInt(row.pest_count, 10);
          return {
            boro,
            pest_count: pestCount,
            population,
            pest_per_100k: Math.round((pestCount / population) * 100_000 * 100) / 100,
          };
        })
        .filter(Boolean)
        .sort((a, b) => b.pest_per_100k - a.pest_per_100k);
    });

    res.json({
      source: 'NYC Open Data — HPD Housing Maintenance Code Violations (csn4-vhvf)',
      timeframe: '2020-01-01 to present',
      fetched_at: new Date().toISOString(),
      data_as_of: new Date(fetchedAt).toISOString(),
      data: summary,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Live pull from NYC Open Data: of the rodent/rat/mice-related violations,
// how many have been certified corrected by the owner (closed) vs. still
// open, per borough.
app.get('/api/rodent-closure-summary', async (req, res) => {
  try {
    const { data: summary, fetchedAt } = await cachedFetch('rodent-closure-summary', async () => {
      const rows = await sodaGroupCount(
        'boro, (certifieddate IS NOT NULL) as is_closed, count(*) as cnt',
        `${DATE_WHERE} AND ${PEST_WHERE}`,
        'boro, is_closed'
      );

      const byBoro = {};
      for (const row of rows) {
        const boro = (row.boro || '').toUpperCase();
        if (!BORO_POPULATION[boro]) continue;
        byBoro[boro] ||= { closed: 0, open: 0 };
        const count = parseInt(row.cnt, 10);
        if (row.is_closed === true) byBoro[boro].closed += count;
        else byBoro[boro].open += count;
      }

      return Object.entries(byBoro)
        .map(([boro, { closed, open }]) => {
          const total = closed + open;
          return {
            boro,
            closed_count: closed,
            open_count: open,
            total,
            closed_pct: Math.round((closed / total) * 1000) / 10,
          };
        })
        .sort((a, b) => b.closed_pct - a.closed_pct);
    });

    res.json({
      source: 'NYC Open Data — HPD Housing Maintenance Code Violations (csn4-vhvf)',
      timeframe: '2020-01-01 to present',
      fetched_at: new Date().toISOString(),
      data_as_of: new Date(fetchedAt).toISOString(),
      data: summary,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Live pull from NYC Open Data: rodent/rat/mice-related violations per zip code
// since 2020, so the front end can offer a "look up your zip" lookup.
app.get('/api/rodent-by-zip', async (req, res) => {
  try {
    const { data: byZip, fetchedAt } = await cachedFetch('rodent-by-zip', async () => {
      const rows = await sodaGroupCount(
        'zip, count(*) as violation_count',
        `${DATE_WHERE} AND ${PEST_WHERE} AND zip IS NOT NULL`,
        'zip'
      );

      return rows
        .map((row) => ({
          zip: (row.zip || '').trim(),
          violation_count: parseInt(row.violation_count, 10),
        }))
        .filter((row) => /^\d{5}$/.test(row.zip))
        .sort((a, b) => b.violation_count - a.violation_count)
        .map((row, i) => ({ ...row, rank: i + 1 }));
    });

    res.json({
      source: 'NYC Open Data — HPD Housing Maintenance Code Violations (csn4-vhvf)',
      timeframe: '2020-01-01 to present',
      fetched_at: new Date().toISOString(),
      data_as_of: new Date(fetchedAt).toISOString(),
      total_zips: byZip.length,
      data: byZip,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/nyc-data', async (req, res) => {
  try {
    const url = new URL(SODA_URL);
    if (!url.searchParams.has('$limit')) {
      url.searchParams.set('$limit', '10');
    }
    for (const [key, value] of Object.entries(req.query)) {
      url.searchParams.set(key, value);
    }

    const headers = { Accept: 'application/json' };
    if (process.env.NYC_USE_AUTH === 'true' && NYC_API_KEY_NAME && NYC_API_KEY_ID) {
      const auth = Buffer.from(`${NYC_API_KEY_NAME}:${NYC_API_KEY_ID}`).toString('base64');
      headers.Authorization = `Basic ${auth}`;
    }

    const response = await fetch(url, { headers });

    if (!response.ok) {
      const text = await response.text();
      return res.status(response.status).json({ error: text });
    }

    const data = await response.json();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running at http://localhost:${PORT}`);
});
