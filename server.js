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

const app = express();

// Live pull from NYC Open Data (HPD Housing Maintenance Code Violations):
// rodent/rat/mice-related violations per borough since 2024, normalized per 100k residents.
app.get('/api/rodent-summary', async (req, res) => {
  try {
    const pestRows = await sodaGroupCount(
      'boro, count(*) as pest_count',
      `${DATE_WHERE} AND ${PEST_WHERE}`,
      'boro'
    );

    const summary = pestRows
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

    res.json({
      source: 'NYC Open Data — HPD Housing Maintenance Code Violations (csn4-vhvf)',
      timeframe: '2020-01-01 to present',
      fetched_at: new Date().toISOString(),
      data: summary,
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
