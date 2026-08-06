import os
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data.cityofnewyork.us/resource/csn4-vhvf.json"
REQUEST_TIMEOUT = 60
DATE_WHERE = (
    "novissueddate >= '2020-01-01T00:00:00' "
    "AND novissueddate < '2027-01-01T00:00:00'"
)
PEST_WHERE = (
    "(upper(novdescription) like '%RODENT%' "
    "OR upper(novdescription) like '%RATS%' "
    "OR upper(novdescription) like '%MICE%')"
)
UNRESOLVED_STATUS = "VIOLATION WILL BE REINSPECTED"

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


def soql_get(headers, select, where, group):
    params = {"$select": select, "$where": where, "$group": group, "$limit": 50000}
    resp = requests.get(BASE_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def main():
    load_env()
    token = os.environ.get("NYC_OPEN_DATA_TOKEN")
    headers = {"Accept": "application/json"}
    if token:
        headers["X-App-Token"] = token
    else:
        print("Warning: NYC_OPEN_DATA_TOKEN not set, requests will be unauthenticated and rate-limited.")

    print("Fetching pest-related violations (RODENT / RATS / MICE), 2020-2026...")
    pest_rows = soql_get(
        headers,
        select="boro, count(*) as pest_count",
        where=f"{DATE_WHERE} AND {PEST_WHERE}",
        group="boro",
    )
    pest_df = pd.DataFrame(pest_rows)
    pest_df["pest_count"] = pest_df["pest_count"].astype(int)

    print("Fetching all violations by status, 2020-2026 (for mismanagement rate)...")
    status_rows = soql_get(
        headers,
        select="boro, currentstatus, count(*) as cnt",
        where=DATE_WHERE,
        group="boro, currentstatus",
    )
    status_df = pd.DataFrame(status_rows)
    status_df["cnt"] = status_df["cnt"].astype(int)

    total_by_boro = status_df.groupby("boro")["cnt"].sum().rename("total_violations")
    unresolved_by_boro = (
        status_df[status_df["currentstatus"] == UNRESOLVED_STATUS]
        .groupby("boro")["cnt"]
        .sum()
        .rename("unresolved_violations")
    )

    summary = (
        pest_df.set_index("boro")
        .join(total_by_boro, how="outer")
        .join(unresolved_by_boro, how="outer")
        .fillna(0)
    )
    summary = summary[summary.index.isin(BORO_POPULATION.keys())]
    summary["population"] = summary.index.map(BORO_POPULATION)
    summary["pest_per_100k"] = (summary["pest_count"] / summary["population"] * 100_000).round(2)
    summary["unresolved_rate_pct"] = (
        summary["unresolved_violations"] / summary["total_violations"] * 100
    ).round(2)

    summary = summary.reset_index().rename(columns={"index": "boro"})
    summary = summary.sort_values("pest_per_100k", ascending=False)
    summary = summary[
        ["boro", "pest_count", "population", "pest_per_100k",
         "total_violations", "unresolved_violations", "unresolved_rate_pct"]
    ]

    print()
    print(summary.to_string(index=False))

    corr = summary["pest_per_100k"].corr(summary["unresolved_rate_pct"])
    print(f"\nCorrelation (pest rate per 100k vs. unresolved-violation rate): {corr:.2f}")
    print(
        "This measures association across only 5 boroughs (n=5) — not proof of "
        "causation, and not a substitute for building-level analysis."
    )

    out_path = Path(__file__).resolve().parent / "rodent_mismanagement_by_borough.csv"
    summary.to_csv(out_path, index=False)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
