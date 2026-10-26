"""Every time granularity a dashboard can ask for is answered by Cube on StarRocks (quarter used to fail: QUARTERS_diff does not exist).

  set -a; . ./.env; set +a
  CUBE_URL=http://localhost:14000/cubejs-api/v1/load uv run --with pytest --with requests --with pyjwt python -I -m pytest cube/tests/test_granularities.py -v
Needs the stack. The buckets are checked against the dates of the data: a quarter starts on the 1st of Jan, Apr, Jul or Oct.
"""
import json
import os
import time

import jwt
import pytest
import requests

CUBE = os.environ.get("CUBE_URL", "http://localhost:4000/cubejs-api/v1/load")
TOKEN = jwt.encode({"user_id": "granularities", "role": "admin", "territories": [], "exp": int(time.time()) + 3600}, os.environ["CUBEJS_API_SECRET"], algorithm="HS256")


def load(query):
    for _ in range(120):
        r = requests.get(CUBE, params={"query": json.dumps(query)}, headers={"Authorization": TOKEN}, timeout=300).json()
        if r.get("error") != "Continue wait":
            return r
        time.sleep(1)
    raise AssertionError("Cube kept waiting")


def series(granularity, **extra):
    return load({"measures": ["internet_sales.revenue"], "timeDimensions": [{"dimension": "dates.full_date", "granularity": granularity, **extra}], "order": {"dates.full_date": "asc"}})


@pytest.mark.parametrize("granularity", ["hour", "day", "week", "month", "quarter", "year"])
def test_every_granularity_is_answered(granularity):
    r = series(granularity, dateRange=["2020-01-01", "2026-12-31"])
    assert "data" in r, r.get("error")
    assert r["data"], f"no rows by {granularity}"


def test_quarters_start_on_quarter_boundaries_and_add_up_to_the_months():
    quarters = series("quarter")["data"]
    months = series("month")["data"]
    starts = {row["dates.full_date.quarter"][5:10] for row in quarters}
    assert starts <= {"01-01", "04-01", "07-01", "10-01"}, starts
    by_quarter = {row["dates.full_date.quarter"][:10]: float(row["internet_sales.revenue"] or 0) for row in quarters}
    rolled = {}
    for row in months:
        y, m = row["dates.full_date.month"][:4], int(row["dates.full_date.month"][5:7])
        key = f"{y}-{(m - 1) // 3 * 3 + 1:02d}-01"
        rolled[key] = rolled.get(key, 0) + float(row["internet_sales.revenue"] or 0)
    assert by_quarter.keys() == rolled.keys()
    for k in by_quarter:
        assert by_quarter[k] == pytest.approx(rolled[k], rel=1e-9), k


def test_a_date_range_narrows_the_series():
    r = series("month", dateRange=["2021-03-01", "2021-03-31"])
    assert all(row["dates.full_date.month"].startswith("2021-03") for row in r["data"])
