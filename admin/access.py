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
        self.sets: dict[str, dict] = {}                              # datasets by id
        self.grants: dict[str, list[dict]] = {}                      # dataset id -> [{type, principal}]
        self.lock = threading.Lock()

    # datasets and who may use them
    def datasets(self) -> list[dict]:
        with self.lock:
            return [{**d, "cubes": list(d["cubes"]), "grants": [dict(g) for g in self.grants.get(d["id"], [])]} for d in sorted(self.sets.values(), key=lambda d: d["name"].lower())]

    def put_dataset(self, id_: str, name: str, description: str, cubes: list[str], grants: list[dict], by: str) -> dict:
        with self.lock:
            self.sets[id_] = {"id": id_, "name": name, "description": description, "cubes": list(cubes), "updated_by": by, "updated_at": _now()}
            self.grants[id_] = [dict(g) for g in grants]
        return next(d for d in self.datasets() if d["id"] == id_)

    def delete_dataset(self, id_: str) -> bool:
        with self.lock:
            self.grants.pop(id_, None)
            return self.sets.pop(id_, None) is not None

    def rename_grants(self, type_: str, old: str, new: str) -> None:
        with self.lock:
            for gs in self.grants.values():
                for g in gs:
                    if g["type"] == type_ and g["principal"] == old:
                        g["principal"] = new

    def drop_grants(self, type_: str, principal: str) -> None:
        with self.lock:
            for k, gs in self.grants.items():
                self.grants[k] = [g for g in gs if not (g["type"] == type_ and g["principal"] == principal)]

    def resolve_input(self) -> tuple[list[dict], list[dict]]:
        """(datasets, grants) in the shape access_resolve.blocked_cubes wants."""
        with self.lock:
            return ([{"id": d["id"], "cubes": list(d["cubes"])} for d in self.sets.values()],
                    [{"object_id": k, "principal_type": g["type"], "principal": g["principal"]} for k, gs in self.grants.items() for g in gs])

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

    # datasets and who may use them
    def datasets(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, name, description, cubes, updated_by, updated_at FROM access.dataset ORDER BY lower(name)")
            rows = cur.fetchall()
            cur.execute("SELECT object_id, principal_type, principal FROM access.\"grant\" WHERE object_type = 'dataset' ORDER BY principal_type, lower(principal)")
            grants: dict[str, list[dict]] = {}
            for g in cur.fetchall():
                grants.setdefault(g["object_id"], []).append({"type": g["principal_type"], "principal": g["principal"]})
        return [{"id": r["id"], "name": r["name"], "description": r["description"], "cubes": list(r["cubes"]), "updated_by": r["updated_by"],
                 "updated_at": r["updated_at"].astimezone(datetime.timezone.utc).isoformat(timespec="seconds"), "grants": grants.get(r["id"], [])} for r in rows]

    def put_dataset(self, id_: str, name: str, description: str, cubes: list[str], grants: list[dict], by: str) -> dict:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO access.dataset (id, name, description, cubes, updated_by) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
                        "name = EXCLUDED.name, description = EXCLUDED.description, cubes = EXCLUDED.cubes, updated_by = EXCLUDED.updated_by, updated_at = now()", (id_, name, description, list(cubes), by))
            cur.execute("DELETE FROM access.\"grant\" WHERE object_type = 'dataset' AND object_id = %s", (id_,))
            for g in grants:
                cur.execute("INSERT INTO access.\"grant\" (object_type, object_id, principal_type, principal, granted_by) VALUES ('dataset', %s, %s, %s, %s)", (id_, g["type"], g["principal"], by))
        return next(d for d in self.datasets() if d["id"] == id_)

    def delete_dataset(self, id_: str) -> bool:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM access.\"grant\" WHERE object_type = 'dataset' AND object_id = %s", (id_,))
            cur.execute("DELETE FROM access.dataset WHERE id = %s", (id_,))
            return cur.rowcount > 0

    def rename_grants(self, type_: str, old: str, new: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE access.\"grant\" SET principal = %s WHERE principal_type = %s AND principal = %s", (new, type_, old))

    def drop_grants(self, type_: str, principal: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM access.\"grant\" WHERE principal_type = %s AND principal = %s", (type_, principal))

    def resolve_input(self) -> tuple[list[dict], list[dict]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, cubes FROM access.dataset")
            datasets = [{"id": r["id"], "cubes": list(r["cubes"])} for r in cur.fetchall()]
            cur.execute("SELECT object_id, principal_type, principal FROM access.\"grant\" WHERE object_type = 'dataset'")
            grants = [{"object_id": r["object_id"], "principal_type": r["principal_type"], "principal": r["principal"]} for r in cur.fetchall()]
        return datasets, grants
