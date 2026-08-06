from pathlib import Path
import os

import pandas as pd
import requests

BASE_URL = "https://data.cityofnewyork.us/resource/csn4-vhvf.json"
REQUEST_TIMEOUT = 60

# Matches the headline borough analysis: rodent/rats/mice, 2020-present.
DATE_WHERE = (
    "novissueddate >= '2020-01-01T00:00:00' "
    "AND novissueddate < '2027-01-01T00:00:00'"
)
PEST_WHERE = (
    "(upper(novdescription) like '%RODENT%' "
    "OR upper(novdescription) like '%RATS%' "
    "OR upper(novdescription) like '%MICE%')"
)


def load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def fetch_zip_counts(token):
    headers = {"Accept": "application/json"}
    if token:
        headers["X-App-Token"] = token

    params = {
        "$select": "boro, zip, count(*) as violation_count",
        "$where": f"{DATE_WHERE} AND {PEST_WHERE}",
        "$group": "boro, zip",
        "$order": "violation_count DESC",
        "$limit": 50000,
    }
    resp = requests.get(BASE_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())


def main():
    load_env()
    token = os.environ.get("NYC_OPEN_DATA_TOKEN")
    if not token:
        print("Warning: NYC_OPEN_DATA_TOKEN not set, requests will be unauthenticated and rate-limited.")

    df = fetch_zip_counts(token)
    if df.empty:
        print("No rodent-related violations found.")
        return

    df["zip"] = df["zip"].fillna("UNKNOWN")
    df["violation_count"] = df["violation_count"].astype(int)
    df = df.sort_values("violation_count", ascending=False)

    print(df.to_string(index=False))

    print("\nTop 5 Bronx ZIP codes:")
    print(df[df["boro"] == "BRONX"].head(5).to_string(index=False))

    out_path = Path(__file__).resolve().parent / "rodent_violations_by_zip.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} boro/zip rows to {out_path}")


if __name__ == "__main__":
    main()
