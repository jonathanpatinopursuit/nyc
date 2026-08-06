import os
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data.cityofnewyork.us/resource/csn4-vhvf.json"
PAGE_SIZE = 5000
MAX_ROWS = 50000
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3

# 2020 Census borough populations
BORO_POPULATION = {
    "BRONX": 1_472_654,
    "BROOKLYN": 2_736_074,
    "MANHATTAN": 1_694_251,
    "QUEENS": 2_405_464,
    "STATEN ISLAND": 495_747,
}


def load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def fetch_rodent_violations(token):
    headers = {"Accept": "application/json"}
    if token:
        headers["X-App-Token"] = token

    where_clause = (
        "upper(novdescription) like '%RODENT%' "
        "AND novissueddate >= '2024-01-01T00:00:00' "
        "AND novissueddate < '2027-01-01T00:00:00'"
    )
    rows = []
    offset = 0

    while offset < MAX_ROWS:
        params = {
            "$select": "boro,novdescription,novissueddate",
            "$where": where_clause,
            "$limit": PAGE_SIZE,
            "$offset": offset,
        }
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.get(BASE_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                break
            except requests.exceptions.RequestException as exc:
                if attempt == MAX_RETRIES:
                    raise
                print(f"  retry {attempt}/{MAX_RETRIES} after error: {exc}")
                time.sleep(2 * attempt)
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        offset += PAGE_SIZE
        if len(batch) < PAGE_SIZE:
            break
        time.sleep(0.2)

    return pd.DataFrame(rows)


def main():
    load_env()
    token = os.environ.get("NYC_OPEN_DATA_TOKEN")
    if not token:
        print("Warning: NYC_OPEN_DATA_TOKEN not set, requests will be unauthenticated and rate-limited.")

    df = fetch_rodent_violations(token)
    if df.empty:
        print("No rodent-related violations found.")
        return

    df = df[df["boro"].isin(BORO_POPULATION.keys())]

    summary = (
        df.groupby("boro")
        .size()
        .reset_index(name="violation_count")
    )
    summary["population"] = summary["boro"].map(BORO_POPULATION)
    summary["violations_per_100k"] = (
        summary["violation_count"] / summary["population"] * 100_000
    ).round(2)
    summary = summary.sort_values("violations_per_100k", ascending=False)

    print(summary.to_string(index=False))

    top = summary.iloc[0]
    print(f"\n{top['boro']} has the highest rodent violation rate: "
          f"{top['violations_per_100k']} per 100k residents "
          f"({top['violation_count']} violations / {top['population']:,} population).")

    out_path = Path(__file__).resolve().parent / "rodent_violations_per_capita.csv"
    summary.to_csv(out_path, index=False)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
