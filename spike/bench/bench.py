"""Per-query latency of the dashboard queries against one Cube instance (Phase 7).

  set -a; . ./.env.spike; set +a
  uv run --with pyjwt --with requests python -I spike/bench/bench.py --label 500m [--runs 15] [--direct-runs 3]
              [--cube http://localhost:4000/cubejs-api/v1/load] [--skip-direct]
For every query: `rollup` = as sent by the dashboard (served by pre-aggregations when one
matches), `direct` = the same query with a filter no rollup carries (answered by StarRocks).
renewQuery forces Cube to ignore its own result cache, so every run is a real execution.
Appends one JSON line per query to spike/bench/results.jsonl.
"""
import argparse
import json
import os
import statistics
import time

import jwt
import requests

from queries import CH, defeat_rollups, panel_queries

ap = argparse.ArgumentParser()
ap.add_argument("--label", required=True)
ap.add_argument("--cube", default="http://localhost:4000/cubejs-api/v1/load")
ap.add_argument("--runs", type=int, default=15)
ap.add_argument("--direct-runs", type=int, default=3)
ap.add_argument("--skip-direct", action="store_true")
ap.add_argument("--fy", type=int, default=2013)
args = ap.parse_args()

TOKEN = jwt.encode({"user_id": "bench", "role": "admin", "territories": [], "exp": int(time.time()) + 6 * 3600},
                   os.environ["CUBEJS_API_SECRET"], algorithm="HS256")


def timed(query):
    t0 = time.time()
    while True:
        r = requests.post(args.cube, json={"query": query, "renewQuery": True}, headers={"Authorization": TOKEN}, timeout=3600)
        body = r.json()
        if body.get("error") == "Continue wait":
            time.sleep(0.2)
            continue
        dt = time.time() - t0
        if r.status_code != 200:
            return dt, None, body.get("error", r.text)[:150]
        return dt, list(body.get("usedPreAggregations", {})), None


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


out = open(os.path.join(os.path.dirname(__file__), "results.jsonl"), "a")
for ch in CH:
    for name, q in panel_queries(ch, fy=args.fy).items():
        for mode, query, runs in (("rollup", q, args.runs), ("direct", defeat_rollups(q), 0 if args.skip_direct else args.direct_runs)):
            if not runs:
                continue
            timed(query)  # warm-up (also builds anything missing)
            times, used, err = [], None, None
            for _ in range(runs):
                dt, used, err = timed(query)
                if err:
                    break
                times.append(dt)
            rec = {"label": args.label, "channel": ch, "query": name, "mode": mode, "runs": len(times),
                   "pre_aggs": [u.split(".")[-1] for u in (used or [])], "error": err}
            if times:
                rec.update(p50=round(statistics.median(times), 3), p95=round(pct(times, 95), 3), max=round(max(times), 3), min=round(min(times), 3))
            out.write(json.dumps(rec) + "\n")
            out.flush()
            served = ",".join(rec["pre_aggs"]) or ("DIRECT" if not err else "ERR")
            print(f"{args.label:5} {ch:8} {name:24} {mode:6} " + (f"p50 {rec['p50']*1000:8.0f} ms  p95 {rec['p95']*1000:8.0f} ms  [{served}]" if times else f"error: {err}"), flush=True)
