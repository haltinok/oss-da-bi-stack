"""Saved queries and result snapshots (Postgres schema `lab`: postgres/init/06_lab_schema.sql) through the least-privilege login `lab_app`; MemoryStore has the same interface for tests.

The store only stores: who may see or change a query is decided in queries.py. Folders are the dashboards' (builder.folders), which this login can only read.
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import threading
import uuid


class NotFound(Exception):
    pass


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(t: datetime.datetime) -> str:
    return t.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


PATCHABLE = ("title", "description", "sql", "folder_id", "shares", "owner")


class MemoryStore:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.snaps: dict[tuple[str, str], dict] = {}
        self.folder_rows: dict[str, dict] = {}                 # tests put folders here (they belong to the builder's schema in Postgres)
        self.lock = threading.Lock()

    def folders(self) -> dict[str, dict]:
        with self.lock:
            return copy.deepcopy(self.folder_rows)

    def list(self) -> list[dict]:
        with self.lock:
            return [copy.deepcopy(r) for r in sorted(self.rows.values(), key=lambda r: r["updated_at"], reverse=True)]

    def get(self, id_) -> dict | None:
        with self.lock:
            return copy.deepcopy(self.rows.get(id_))

    def count_owned(self, owner) -> int:
        with self.lock:
            return sum(1 for r in self.rows.values() if r["owner"] == owner)

    def create(self, *, owner, title, description, sql, folder_id, shares) -> dict:
        with self.lock:
            now = _iso(_now())
            row = {"id": str(uuid.uuid4()), "owner": owner, "title": title, "description": description, "sql": sql, "folder_id": folder_id, "shares": copy.deepcopy(shares), "created_at": now, "updated_at": now}
            self.rows[row["id"]] = row
            return copy.deepcopy(row)

    def patch(self, id_, **fields) -> dict:
        with self.lock:
            row = self.rows.get(id_)
            if row is None:
                raise NotFound(id_)
            for k, v in fields.items():
                if k not in PATCHABLE:
                    raise ValueError(k)
                row[k] = copy.deepcopy(v)
            row["updated_at"] = _iso(_now())
            return copy.deepcopy(row)

    def delete(self, id_) -> None:
        with self.lock:
            if self.rows.pop(id_, None) is None:
                raise NotFound(id_)
            for k in [k for k in self.snaps if k[0] == id_]:
                del self.snaps[k]

    def transfer(self, from_owner, to_owner) -> int:
        with self.lock:
            n = 0
            for r in self.rows.values():
                if r["owner"] == from_owner:
                    r["owner"], n = to_owner, n + 1
            return n

    def put_snapshot(self, id_, runner, out: dict, hours: float) -> dict:
        with self.lock:
            now = _now()
            snap = {"query_id": id_, "runner": runner, "columns": copy.deepcopy(out["columns"]), "rows": copy.deepcopy(out["rows"]), "row_count": out["row_count"], "truncated": out["truncated"], "ms": out.get("ms", 0),
                    "created_at": _iso(now), "expires_at": _iso(now + datetime.timedelta(hours=hours))}
            self.snaps[(id_, runner)] = snap
            return copy.deepcopy(snap)

    def snapshot(self, id_, runner) -> dict | None:
        with self.lock:
            snap = self.snaps.get((id_, runner))
            if snap and snap["expires_at"] <= _iso(_now()):
                del self.snaps[(id_, runner)]
                return None
            return copy.deepcopy(snap)

    def snapshot_runners(self, id_) -> list[str]:
        with self.lock:
            return sorted(r for (q, r) in self.snaps if q == id_)

    def purge(self) -> int:
        with self.lock:
            gone = [k for k, v in self.snaps.items() if v["expires_at"] <= _iso(_now())]
            for k in gone:
                del self.snaps[k]
            return len(gone)


class PgStore:
    """Postgres. One short connection per call: the lab is low traffic and a connection never outlives a request."""

    def __init__(self, **dsn):
        self.dsn = dsn

    @classmethod
    def from_env(cls) -> "PgStore | None":
        pw = os.environ.get("LAB_DB_PASSWORD", "")
        if not pw or pw == "REPLACE_ME":
            return None
        return cls(host=os.environ.get("LAB_PG_HOST", "postgres"), port=int(os.environ.get("LAB_PG_PORT", "5432")), dbname=os.environ.get("LAB_PG_DB", "postgres"),
                   user=os.environ.get("LAB_PG_USER", "lab_app"), password=pw, connect_timeout=5)

    def _conn(self):
        import psycopg2
        import psycopg2.extras
        return psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **self.dsn)

    @staticmethod
    def _row(r) -> dict | None:
        if r is None:
            return None
        r = dict(r)
        for k in ("created_at", "updated_at", "expires_at"):
            if k in r and r[k] is not None:
                r[k] = _iso(r[k])
        for k in ("shares", "columns", "rows"):
            if k in r and isinstance(r[k], str):
                r[k] = json.loads(r[k])
        return r

    def folders(self) -> dict[str, dict]:
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT id, name, owner, shares FROM builder.folders")
                return {r["id"]: self._row(r) for r in cur.fetchall()}
        except Exception:                                           # noqa: BLE001 (no builder schema: no folders, the lab still works)
            return {}

    def list(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM lab.saved_queries ORDER BY updated_at DESC LIMIT 1000")
            return [self._row(r) for r in cur.fetchall()]

    def get(self, id_) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM lab.saved_queries WHERE id = %s", (id_,))
            return self._row(cur.fetchone())

    def count_owned(self, owner) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM lab.saved_queries WHERE owner = %s", (owner,))
            return cur.fetchone()["n"]

    def create(self, *, owner, title, description, sql, folder_id, shares) -> dict:
        import psycopg2.extras
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO lab.saved_queries (id, owner, title, description, sql, folder_id, shares) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                        (str(uuid.uuid4()), owner, title, description, sql, folder_id, psycopg2.extras.Json(shares)))
            return self._row(cur.fetchone())

    def patch(self, id_, **fields) -> dict:
        import psycopg2.extras
        sets, args = [], []
        for k, v in fields.items():
            if k not in PATCHABLE:
                raise ValueError(k)
            sets.append(f"{k} = %s")
            args.append(psycopg2.extras.Json(v) if k == "shares" else v)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE lab.saved_queries SET {', '.join(sets)}, updated_at = now() WHERE id = %s RETURNING *", (*args, id_))
            row = cur.fetchone()
            if row is None:
                raise NotFound(id_)
            return self._row(row)

    def delete(self, id_) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM lab.saved_queries WHERE id = %s", (id_,))
            if cur.rowcount == 0:
                raise NotFound(id_)

    def transfer(self, from_owner, to_owner) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE lab.saved_queries SET owner = %s WHERE owner = %s", (to_owner, from_owner))
            return cur.rowcount

    def put_snapshot(self, id_, runner, out: dict, hours: float) -> dict:
        import psycopg2.extras
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO lab.snapshots (query_id, runner, columns, rows, row_count, truncated, ms, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s, now() + make_interval(secs => %s)) "
                        "ON CONFLICT (query_id, runner) DO UPDATE SET columns = EXCLUDED.columns, rows = EXCLUDED.rows, row_count = EXCLUDED.row_count, truncated = EXCLUDED.truncated, ms = EXCLUDED.ms, "
                        "created_at = now(), expires_at = EXCLUDED.expires_at RETURNING *",
                        (id_, runner, psycopg2.extras.Json(out["columns"]), psycopg2.extras.Json(out["rows"]), out["row_count"], out["truncated"], out.get("ms", 0), hours * 3600))
            return self._row(cur.fetchone())

    def snapshot(self, id_, runner) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM lab.snapshots WHERE query_id = %s AND runner = %s AND expires_at > now()", (id_, runner))
            return self._row(cur.fetchone())

    def snapshot_runners(self, id_) -> list[str]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT runner FROM lab.snapshots WHERE query_id = %s ORDER BY runner", (id_,))
            return [r["runner"] for r in cur.fetchall()]

    def purge(self) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM lab.snapshots WHERE expires_at <= now()")
            return cur.rowcount
