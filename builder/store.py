"""Saved dashboards: who saved what, who may open it, and its last versions.

PgStore keeps them in Postgres (schema `builder`: postgres/init/02_builder_schema.sql) through the least-privilege login `builder_app`; MemoryStore has the same
interface for tests and for the mock stack. The store only stores: who may see a dashboard and whether a spec is valid for a role are decided in saved.py.
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import threading
import uuid

KEEP_VERSIONS = 10
PATCHABLE = ("shares", "folder_id", "owner", "deleted_at")
TRASH_DAYS = 30


class NotFound(Exception):
    pass


class Limit(Exception):
    pass


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.versions: dict[str, list[dict]] = {}
        self.folder_rows: dict[str, dict] = {}
        self.lock = threading.Lock()

    def create(self, *, owner, owner_role, title, description, yaml, visibility, shared_roles, max_saved) -> dict:
        with self.lock:
            if sum(1 for r in self.rows.values() if r["owner"] == owner and not r.get("deleted_at")) >= max_saved:
                raise Limit(f"You can keep {max_saved} saved dashboards; delete one first.")
            now, id_ = _now(), str(uuid.uuid4())
            row = {"id": id_, "owner": owner, "owner_role": owner_role, "title": title, "description": description, "yaml": yaml, "visibility": visibility,
                   "shared_roles": list(shared_roles), "shares": [], "folder_id": None, "deleted_at": None, "version": 1, "created_at": now, "updated_at": now}
            self.rows[id_] = row
            self.versions[id_] = [{"version": 1, "title": title, "yaml": yaml, "saved_by": owner, "saved_at": now}]
            return copy.deepcopy(row)

    def get(self, id_) -> dict | None:
        with self.lock:
            return copy.deepcopy(self.rows.get(id_))

    def list(self, *, owner=None, deleted=False) -> list[dict]:
        """The saved dashboards (newest first); `deleted=True` lists the ones in the trash instead."""
        with self.lock:
            rows = [r for r in self.rows.values() if (owner is None or r["owner"] == owner) and bool(r.get("deleted_at")) == deleted]
            return [copy.deepcopy(r) for r in sorted(rows, key=lambda r: r["updated_at"], reverse=True)]

    def patch(self, id_, **fields) -> dict:
        """Change who may see it, where it lives, who owns it, or whether it is in the trash: `shares`, `folder_id`, `owner`, `deleted_at` (an ISO time or None). Not a new version."""
        with self.lock:
            row = self.rows.get(id_)
            if row is None:
                raise NotFound(id_)
            for k, v in fields.items():
                if k not in PATCHABLE:
                    raise ValueError(k)
                row[k] = copy.deepcopy(v)
            return copy.deepcopy(row)

    def purge(self, before: str) -> int:
        """Remove what has been in the trash since before `before` (an ISO time)."""
        with self.lock:
            gone = [i for i, r in self.rows.items() if r.get("deleted_at") and r["deleted_at"] < before]
            for i in gone:
                del self.rows[i]
                self.versions.pop(i, None)
            return len(gone)

    def transfer(self, from_owner: str, to_owner: str) -> int:
        with self.lock:
            n = 0
            for r in self.rows.values():
                if r["owner"] == from_owner:
                    r["owner"], n = to_owner, n + 1
            return n

    # folders
    def folders(self) -> list[dict]:
        with self.lock:
            return [copy.deepcopy(f) for f in sorted(self.folder_rows.values(), key=lambda f: f["name"].lower())]

    def folder(self, id_) -> dict | None:
        with self.lock:
            return copy.deepcopy(self.folder_rows.get(id_))

    def create_folder(self, *, owner, name) -> dict:
        with self.lock:
            f = {"id": str(uuid.uuid4()), "name": name, "owner": owner, "shares": [], "created_at": _now()}
            self.folder_rows[f["id"]] = f
            return copy.deepcopy(f)

    def patch_folder(self, id_, *, name=None, shares=None) -> dict:
        with self.lock:
            f = self.folder_rows.get(id_)
            if f is None:
                raise NotFound(id_)
            if name is not None:
                f["name"] = name
            if shares is not None:
                f["shares"] = copy.deepcopy(shares)
            return copy.deepcopy(f)

    def delete_folder(self, id_) -> None:
        with self.lock:
            if self.folder_rows.pop(id_, None) is None:
                raise NotFound(id_)
            for r in self.rows.values():
                if r.get("folder_id") == id_:
                    r["folder_id"] = None                                    # what was in it stays, outside any folder

    def update(self, id_, *, by, title=None, description=None, yaml=None, visibility=None, shared_roles=None, owner_role=None) -> dict:
        with self.lock:
            row = self.rows.get(id_)
            if row is None:
                raise NotFound(id_)
            if yaml is not None and yaml != row["yaml"]:
                row["version"] += 1
                row["yaml"] = yaml
                self.versions[id_].append({"version": row["version"], "title": title or row["title"], "yaml": yaml, "saved_by": by, "saved_at": _now()})
                self.versions[id_] = self.versions[id_][-KEEP_VERSIONS:]
            for k, v in (("title", title), ("description", description), ("visibility", visibility), ("owner_role", owner_role)):
                if v is not None:
                    row[k] = v
            if shared_roles is not None:
                row["shared_roles"] = list(shared_roles)
            row["updated_at"] = _now()
            return copy.deepcopy(row)

    def delete(self, id_) -> None:
        with self.lock:
            if self.rows.pop(id_, None) is None:
                raise NotFound(id_)
            self.versions.pop(id_, None)

    def list_versions(self, id_) -> list[dict]:
        with self.lock:
            return [{k: v for k, v in x.items() if k != "yaml"} for x in reversed(self.versions.get(id_, []))]

    def get_version(self, id_, version) -> dict | None:
        with self.lock:
            return next((copy.deepcopy(x) for x in self.versions.get(id_, []) if x["version"] == version), None)


class PgStore:
    """Postgres. One short connection per call: the builder is low traffic and a connection never outlives a request."""

    def __init__(self, **dsn):
        self.dsn = dsn

    @classmethod
    def from_env(cls) -> "PgStore | None":
        pw = os.environ.get("BUILDER_DB_PASSWORD", "")
        if not pw or pw == "REPLACE_ME":
            return None
        return cls(host=os.environ.get("BUILDER_PG_HOST", "postgres"), port=int(os.environ.get("BUILDER_PG_PORT", "5432")), dbname=os.environ.get("BUILDER_PG_DB", "postgres"),
                   user=os.environ.get("BUILDER_PG_USER", "builder_app"), password=pw, connect_timeout=5)

    def _conn(self):
        import psycopg2
        import psycopg2.extras
        return psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **self.dsn)

    @staticmethod
    def _row(r) -> dict | None:
        if r is None:
            return None
        r = dict(r)
        for k in ("created_at", "updated_at", "saved_at", "deleted_at"):
            if k in r and r[k] is not None:
                r[k] = r[k].astimezone(datetime.timezone.utc).isoformat(timespec="seconds")
        if "shared_roles" in r:
            r["shared_roles"] = list(r["shared_roles"])
        if "shares" in r and not isinstance(r["shares"], list):
            r["shares"] = json.loads(r["shares"]) if r["shares"] else []
        return r

    def create(self, *, owner, owner_role, title, description, yaml, visibility, shared_roles, max_saved) -> dict:
        id_ = str(uuid.uuid4())
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"builder-save-{owner}",))       # two saves at once must not both pass the limit
            cur.execute("SELECT count(*) AS n FROM builder.saved_dashboards WHERE owner = %s AND deleted_at IS NULL", (owner,))
            if cur.fetchone()["n"] >= max_saved:
                raise Limit(f"You can keep {max_saved} saved dashboards; delete one first.")
            cur.execute("INSERT INTO builder.saved_dashboards (id, owner, owner_role, title, description, yaml, visibility, shared_roles) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                        (id_, owner, owner_role, title, description, yaml, visibility, list(shared_roles)))
            row = cur.fetchone()
            cur.execute("INSERT INTO builder.saved_versions (dashboard_id, version, title, yaml, saved_by) VALUES (%s,1,%s,%s,%s)", (id_, title, yaml, owner))
            return self._row(row)

    def get(self, id_) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM builder.saved_dashboards WHERE id = %s", (id_,))
            return self._row(cur.fetchone())

    def list(self, *, owner=None, deleted=False) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            where = ("deleted_at IS NOT NULL" if deleted else "deleted_at IS NULL") + (" AND owner = %s" if owner is not None else "")
            cur.execute(f"SELECT * FROM builder.saved_dashboards WHERE {where} ORDER BY updated_at DESC LIMIT 500", (owner,) if owner is not None else ())
            return [self._row(r) for r in cur.fetchall()]

    def patch(self, id_, **fields) -> dict:
        import psycopg2.extras
        sets, args = [], []
        for k, v in fields.items():
            if k not in PATCHABLE:
                raise ValueError(k)
            if k == "shares":
                v = psycopg2.extras.Json(v)
            sets.append(f"{k} = %s")
            args.append(v)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE builder.saved_dashboards SET {', '.join(sets)} WHERE id = %s RETURNING *", (*args, id_))
            row = cur.fetchone()
            if row is None:
                raise NotFound(id_)
            return self._row(row)

    def purge(self, before: str) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM builder.saved_dashboards WHERE deleted_at IS NOT NULL AND deleted_at < %s", (before,))
            return cur.rowcount

    def transfer(self, from_owner: str, to_owner: str) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE builder.saved_dashboards SET owner = %s WHERE owner = %s", (to_owner, from_owner))
            return cur.rowcount

    # folders
    def folders(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM builder.folders ORDER BY lower(name) LIMIT 1000")
            return [self._row(r) for r in cur.fetchall()]

    def folder(self, id_) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM builder.folders WHERE id = %s", (id_,))
            return self._row(cur.fetchone())

    def create_folder(self, *, owner, name) -> dict:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO builder.folders (id, owner, name) VALUES (%s, %s, %s) RETURNING *", (str(uuid.uuid4()), owner, name))
            return self._row(cur.fetchone())

    def patch_folder(self, id_, *, name=None, shares=None) -> dict:
        import psycopg2.extras
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE builder.folders SET name = COALESCE(%s, name), shares = COALESCE(%s, shares) WHERE id = %s RETURNING *",
                        (name, psycopg2.extras.Json(shares) if shares is not None else None, id_))
            row = cur.fetchone()
            if row is None:
                raise NotFound(id_)
            return self._row(row)

    def delete_folder(self, id_) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE builder.saved_dashboards SET folder_id = NULL WHERE folder_id = %s", (id_,))
            cur.execute("DELETE FROM builder.folders WHERE id = %s", (id_,))
            if cur.rowcount == 0:
                raise NotFound(id_)

    def update(self, id_, *, by, title=None, description=None, yaml=None, visibility=None, shared_roles=None, owner_role=None) -> dict:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM builder.saved_dashboards WHERE id = %s FOR UPDATE", (id_,))
            row = cur.fetchone()
            if row is None:
                raise NotFound(id_)
            version = row["version"]
            if yaml is not None and yaml != row["yaml"]:
                version += 1
                cur.execute("INSERT INTO builder.saved_versions (dashboard_id, version, title, yaml, saved_by) VALUES (%s,%s,%s,%s,%s)", (id_, version, title or row["title"], yaml, by))
                cur.execute("DELETE FROM builder.saved_versions WHERE dashboard_id = %s AND version <= %s", (id_, version - KEEP_VERSIONS))
            cur.execute("""UPDATE builder.saved_dashboards SET title = COALESCE(%s, title), description = COALESCE(%s, description), yaml = COALESCE(%s, yaml),
                           visibility = COALESCE(%s, visibility), shared_roles = COALESCE(%s, shared_roles), owner_role = COALESCE(%s, owner_role),
                           version = %s, updated_at = now() WHERE id = %s RETURNING *""",
                        (title, description, yaml, visibility, list(shared_roles) if shared_roles is not None else None, owner_role, version, id_))
            return self._row(cur.fetchone())

    def delete(self, id_) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM builder.saved_dashboards WHERE id = %s", (id_,))
            if cur.rowcount == 0:
                raise NotFound(id_)

    def list_versions(self, id_) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT version, title, saved_by, saved_at FROM builder.saved_versions WHERE dashboard_id = %s ORDER BY version DESC", (id_,))
            return [self._row(r) for r in cur.fetchall()]

    def get_version(self, id_, version) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM builder.saved_versions WHERE dashboard_id = %s AND version = %s", (id_, version))
            return self._row(cur.fetchone())
