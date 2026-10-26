"""`dashspec lint`: does a Cube pre-aggregation (rollup) serve every query a dashboard sends? A query no rollup serves scans the fact table:
fine on the live mart, seconds at 250M rows (spike/results.md). The check asks Cube to plan each query (GET /v1/sql) and reads which
pre-aggregations the plan uses; it runs nothing."""
import json
import urllib.error
import urllib.parse
import urllib.request

from .queries import panel_queries


def filter_states(spec):
    """No filter, each filter alone, and every filter at once: the states a reader moves through (a value only has to be a value)."""
    ids = [f["id"] for f in spec.get("filters", [])]
    return [("no filter", {})] + [(f"filter '{i}'", {i: "x"}) for i in ids] + ([("every filter", {i: "x" for i in ids})] if len(ids) > 1 else [])


def describe(q):
    dims = [*q.get("dimensions", []), *(f"{t['dimension']}.{t['granularity']}" for t in q.get("timeDimensions", []) if t.get("granularity"))]
    return f"{', '.join(q.get('measures', [])) or '(no measures)'}" + (f" by {', '.join(dims)}" if dims else "")


def lint(spec, plan):
    """plan(query) -> list of the pre-aggregations Cube would use, [] when none, None when Cube did not say. -> [(severity, message)]."""
    out, seen = [], {}
    for p in spec["panels"]:
        for label, values in filter_states(spec):
            for item in panel_queries(spec, p, values):
                key = json.dumps(item["query"], sort_keys=True)
                if key not in seen:
                    seen[key] = plan(item["query"])
                used = seen[key]
                where = f"panel '{p['id']}' ({p['type']})"
                if used is None:
                    out.append(("unknown", f"{where}: Cube did not say which pre-aggregation serves '{describe(item['query'])}' ({label})"))
                elif not used:
                    out.append(("warning", f"{where}: no pre-aggregation serves '{describe(item['query'])}' ({label}); it scans the fact table"))
    return list(dict.fromkeys(out))      # the same query under several states is reported once


def cube_planner(url, token):
    """A plan() that asks a running Cube (a Cube JWT; `admin` sees every cube)."""
    def plan(query):
        req = urllib.request.Request(f"{url.rstrip('/')}/cubejs-api/v1/sql?{urllib.parse.urlencode({'query': json.dumps(query)})}", headers={"Authorization": token})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (a URL the operator passed)
                body = json.load(r)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Cube refused to plan {describe(query)}: HTTP {e.code} {e.read().decode(errors='replace')[:200]}") from None
        sql = body.get("sql", body)
        return sql.get("preAggregations") if isinstance(sql, dict) and "preAggregations" in sql else None
    return plan
