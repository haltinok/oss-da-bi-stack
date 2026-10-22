"""Concurrent dashboard users against Cube with row-level security on (Phase 7).

  set -a; . ./.env.spike; set +a
  uv run --with pyjwt --with requests python -I spike/bench/load.py --label 500m --users 1,10,25 --duration 90
Each virtual user signs in through Keycloak -> auth service as admin, na_manager or de_rep
(round robin, so every run mixes all three roles and the territory filter), then loops:
pick a dashboard panel query for a random channel, send it, think 0.5-1.5 s.
The query mix is the panels that pre-aggregations are expected to serve (no cross-filter
combinations that fall back to a direct scan; spike/bench/bench.py measures those).
Also samples docker stats for StarRocks / Cube / Cube Store while the load runs.
Appends one JSON line per user count to spike/bench/load-results.jsonl.
"""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import threading
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I drops the script dir
from queries import CH, panel_queries

ap = argparse.ArgumentParser()
ap.add_argument("--label", required=True)
ap.add_argument("--cube", default="http://localhost:4000/cubejs-api/v1/load")
ap.add_argument("--users", default="1,10,25")
ap.add_argument("--duration", type=int, default=90)
ap.add_argument("--roles", default="admin,na_manager,de_rep", help="comma list; users are assigned round robin")
ap.add_argument("--note", default="")
args = ap.parse_args()

KEYCLOAK, AUTH, PASSWORD = "http://localhost:8180", "http://localhost:8200", os.environ["TEST_USER_PASSWORD"]
ROLES = args.roles.split(",")
SKIP = {"territories_fy_category"}          # known direct-scan shape


def login(user):
    kc = requests.post(f"{KEYCLOAK}/realms/spike/protocol/openid-connect/token", timeout=30,
                       data={"grant_type": "password", "client_id": "dashboard", "username": user, "password": PASSWORD}).json()
    r = requests.post(f"{AUTH}/token", headers={"Authorization": f"Bearer {kc['access_token']}"}, timeout=30).json()
    return r["token"]


tokens = {u: (login(u), time.time()) for u in ROLES}


def token(user):
    t, at = tokens[user]
    if time.time() - at > 600:
        t = login(user)
        tokens[user] = (t, time.time())
    return t


# every (user, channel) query set, built once
QUERIES = {(u, ch): [(n, q) for n, q in panel_queries(ch, profit=(u != "de_rep"),
           region="Germany" if u == "de_rep" else "Canada").items() if n not in SKIP]
           for u in ROLES for ch in CH}


def sampler(stop, samples):
    names = ["spike-starrocks-1", "spike-cube-1", "spike-cubestore-1", "spike-cubestore-worker-1"]
    while not stop.is_set():
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"] + names, capture_output=True, text=True).stdout
        row = {}
        for line in out.splitlines():
            d = json.loads(line)
            mem = d["MemUsage"].split("/")[0].strip()
            unit = {"GiB": 1024, "MiB": 1, "KiB": 1 / 1024, "B": 1 / 1048576}
            val = next(float(mem[:-len(u)]) * k for u, k in unit.items() if mem.endswith(u))
            row[d["Name"]] = (float(d["CPUPerc"].rstrip("%")), val)
        samples.append(row)


def vuser(idx, deadline, lat, errs, direct):
    user = ROLES[idx % len(ROLES)]
    rnd = random.Random(idx)
    while time.time() < deadline:
        ch = rnd.choice(list(CH))
        name, q = rnd.choice(QUERIES[(user, ch)])
        t0 = time.time()
        try:
            while True:
                r = requests.post(args.cube, json={"query": q}, headers={"Authorization": token(user)}, timeout=600)
                body = r.json()
                if body.get("error") == "Continue wait":
                    time.sleep(0.05)
                    continue
                break
            dt = time.time() - t0
            if r.status_code == 200:
                lat.append(dt)
                if not body.get("usedPreAggregations"):
                    direct.append(name)
            else:
                errs.append((name, r.status_code, str(body.get("error"))[:80]))
        except Exception as e:  # noqa: BLE001
            errs.append((name, "exc", str(e)[:80]))
        time.sleep(rnd.uniform(0.5, 1.5))


out = open(os.path.join(os.path.dirname(__file__), "load-results.jsonl"), "a")
for n in [int(x) for x in args.users.split(",")]:
    lat, errs, direct, samples = [], [], [], []
    stop = threading.Event()
    s = threading.Thread(target=sampler, args=(stop, samples), daemon=True)
    s.start()
    deadline = time.time() + args.duration
    threads = [threading.Thread(target=vuser, args=(i, deadline, lat, errs, direct)) for i in range(n)]
    t0 = time.time()
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.time() - t0
    stop.set()
    s.join(timeout=15)
    srt = sorted(lat)
    def q(p, srt=srt):
        return srt[min(len(srt) - 1, int(p / 100 * (len(srt) - 1)))] if srt else None

    rec = {"label": args.label, "note": args.note, "roles": ROLES, "users": n, "duration_s": round(wall), "requests": len(lat) + len(errs), "ok": len(lat), "errors": len(errs),
           "rps": round(len(lat) / wall, 2), "p50": round(statistics.median(lat), 3) if lat else None,
           "p95": round(q(95), 3) if lat else None, "p99": round(q(99), 3) if lat else None, "max": round(max(lat), 3) if lat else None,
           "direct_share": round(len(direct) / len(lat), 3) if lat else None, "error_sample": errs[:3]}
    for svc in ("spike-starrocks-1", "spike-cube-1", "spike-cubestore-1", "spike-cubestore-worker-1"):
        cpu = [r[svc][0] for r in samples if svc in r]
        mem = [r[svc][1] for r in samples if svc in r]
        if cpu:
            rec[svc.replace("spike-", "").replace("-1", "")] = {"cpu_avg": round(statistics.mean(cpu), 1), "cpu_max": round(max(cpu), 1), "mem_max_mib": round(max(mem))}
    out.write(json.dumps(rec) + "\n")
    out.flush()
    print(json.dumps(rec), flush=True)
