"""The row-level rules the console edits (Postgres schema `access`: postgres/init/04_access_schema.sql), through the least-privilege login `access_admin`.

A rule: for a user (by username) or a group (by name), the sales territories they may see. MemoryStore has the same interface for tests.
"""
from __future__ import annotations

import datetime
import os
import threading

TYPES = ("user", "group")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class MemoryRules:
    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}
        self.lock = threading.Lock()

    def list(self) -> list[dict]:
        with self.lock:
            return sorted((dict(r) for r in self.rows.values()), key=lambda r: (r["type"], r["principal"].lower()))

    def put(self, type_: str, principal: str, values: list[str], by: str) -> dict:
        with self.lock:
            row = {"type": type_, "principal": principal, "values": list(values), "updated_by": by, "updated_at": _now()}
            self.rows[(type_, principal)] = row
            return dict(row)

    def delete(self, type_: str, principal: str) -> bool:
        with self.lock:
            return self.rows.pop((type_, principal), None) is not None

    def rename(self, type_: str, old: str, new: str) -> None:
        with self.lock:
            row = self.rows.pop((type_, old), None)
            if row:
                row["principal"] = new
                self.rows[(type_, new)] = row


class PgRules:
    """Postgres. One short connection per call."""

    def __init__(self, **dsn):
        self.dsn = dsn

    @classmethod
    def from_env(cls) -> "PgRules | None":
        pw = os.environ.get("ADMIN_DB_PASSWORD", "")
        if not pw or pw == "REPLACE_ME":
            return None
        return cls(host=os.environ.get("ADMIN_PG_HOST", "postgres"), port=int(os.environ.get("ADMIN_PG_PORT", "5432")), dbname=os.environ.get("ADMIN_PG_DB", "postgres"),
                   user=os.environ.get("ADMIN_PG_USER", "access_admin"), password=pw, connect_timeout=5)

    def _conn(self):
        import psycopg2
        import psycopg2.extras
        return psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **self.dsn)

    @staticmethod
    def _row(r: dict) -> dict:
        return {"type": r["principal_type"], "principal": r["principal"], "values": list(r["values"]), "updated_by": r["updated_by"],
                "updated_at": r["updated_at"].astimezone(datetime.timezone.utc).isoformat(timespec="seconds")}

    def list(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute('SELECT principal_type, principal, "values", updated_by, updated_at FROM access.rls_rule ORDER BY principal_type, lower(principal)')
            return [self._row(r) for r in cur.fetchall()]

    def put(self, type_: str, principal: str, values: list[str], by: str) -> dict:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute('INSERT INTO access.rls_rule (principal_type, principal, "values", updated_by) VALUES (%s, %s, %s, %s) '
                        'ON CONFLICT (principal_type, principal, dimension) DO UPDATE SET "values" = EXCLUDED."values", updated_by = EXCLUDED.updated_by, updated_at = now() '
                        'RETURNING principal_type, principal, "values", updated_by, updated_at', (type_, principal, list(values), by))
            return self._row(cur.fetchone())

    def delete(self, type_: str, principal: str) -> bool:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM access.rls_rule WHERE principal_type = %s AND principal = %s", (type_, principal))
            return cur.rowcount > 0

    def rename(self, type_: str, old: str, new: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE access.rls_rule SET principal = %s WHERE principal_type = %s AND principal = %s", (new, type_, old))
