"""End-to-end freshness: time from a source insert to the figure being visible through Cube.

  set -a; . ./.env; set +a
  CUBE_URL=http://localhost:4000/cubejs-api/v1/load \
  uv run --with pyjwt --with requests python -I spike/bench/freshness.py --samples 8

Each sample forces the Faker simulator to create one new order in postgres_active
(SIM_ORDER_CHANCE=1, run inside the Airflow container), then polls a rollup-served Cube query
(total internet order lines) until the count goes up. The insert happens at a random offset into
the 5-minute pipeline cycle, so the samples cover the whole distribution: lag is roughly
(wait for the next cycle: 0-5 min) + (ingest + dbt build, ~35 s at demo volume) + (Cube refresh, ~1 min).
The pipeline can run no faster than its schedule, so this is the floor for any micro-batch design.
"""
import argparse
import os
import random
import statistics
import subprocess
import time

import jwt
import requests

ap = argparse.ArgumentParser()
ap.add_argument("--samples", type=int, default=8)
ap.add_argument("--cube", default=os.environ.get("CUBE_URL", "http://localhost:4000/cubejs-api/v1/load"))
ap.add_argument("--container", default="oss_airflow_scheduler")
ap.add_argument("--timeout", type=int, default=1200)
ap.add_argument("--max-offset", type=int, default=300, help="random wait (s) before each insert")
args = ap.parse_args()

TOKEN = jwt.encode({"user_id": "fresh", "role": "admin", "territories": [], "exp": int(time.time()) + 6 * 3600},
                   os.environ["CUBEJS_API_SECRET"], algorithm="HS256")
QUERY = {"measures": ["internet_sales.lines", "internet_sales.revenue"]}


def cube_lines() -> int:
    while True:
        r = requests.post(args.cube, json={"query": QUERY, "renewQuery": True}, headers={"Authorization": TOKEN}, timeout=300).json()
        if r.get("error") == "Continue wait":
            time.sleep(0.5)
            continue
        return int(r["data"][0]["internet_sales.lines"])


def insert_order() -> str:
    out = subprocess.run(
        ["docker", "exec", "-e", "SIM_ORDER_CHANCE=1", args.container, "python", "/opt/airflow/scripts/simulate_adventureworks.py"],
        capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


lags = []
for i in range(1, args.samples + 1):
    time.sleep(random.uniform(0, args.max_offset))
    base = cube_lines()
    t0 = time.time()
    msg = insert_order()
    seen = None
    while time.time() - t0 < args.timeout:
        if cube_lines() > base:
            seen = time.time() - t0
            break
        time.sleep(5)
    lags.append(seen)
    print(f"sample {i}/{args.samples}: {'%.0f s' % seen if seen else 'NOT SEEN within %d s' % args.timeout}  ({msg})", flush=True)
    # let the new order become visible everywhere before the next sample
    time.sleep(2)

ok = sorted(x for x in lags if x)
if ok:
    p = lambda q: ok[min(len(ok) - 1, int(round(q / 100 * (len(ok) - 1))))]  # noqa: E731
    print(f"\nfreshness over {len(ok)} samples: p50 {statistics.median(ok):.0f} s, p95 {p(95):.0f} s, max {max(ok):.0f} s, "
          f"min {min(ok):.0f} s; not seen: {len(lags) - len(ok)}")
