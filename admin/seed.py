"""The dbt seed's territories (StarRocks `rls.user_regions`), read-only, for the regions list and the "what will this person see" preview.

The same table the auth service reads when no rule applies to a person. Without StarRocks settings (or when it is unreachable) the answers are None: unknown.
"""
from __future__ import annotations

import os
import re


class Seed:
    def __init__(self, host: str, port: int, user: str, password: str, table: str):
        self.host, self.port, self.user, self.password, self.table = host, port, user, password, table

    @classmethod
    def from_env(cls) -> "Seed | None":
        pw, user = os.environ.get("AUTH_DB_PASSWORD", ""), os.environ.get("AUTH_DB_USER", "")
        if not pw or not user:
            return None
        dataset = os.environ.get("DATASET", "live").lower()
        if not re.fullmatch(r"[a-z0-9]+", dataset):
            return None
        suffix = "" if dataset in ("live", "both") else f"_{dataset}"
        table = os.environ.get("AUTH_REGIONS_TABLE") or f"rls{suffix}.user_regions"
        if not re.fullmatch(r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+", table):
            return None
        return cls(os.environ.get("STARROCKS_HOST", "starrocks-fe"), int(os.environ.get("STARROCKS_PORT", "9030")), user, pw, table)

    def _query(self, sql: str, args=()) -> list[str] | None:
        import pymysql
        try:
            conn = pymysql.connect(host=self.host, port=self.port, user=self.user, password=self.password, connect_timeout=4)
        except pymysql.MySQLError:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return [r[0] for r in cur.fetchall()]
        except pymysql.MySQLError:                                       # dbt drops and recreates the table for a moment on every build
            return None
        finally:
            conn.close()

    def regions(self) -> list[str] | None:
        return self._query(f"select distinct region from {self.table} order by 1")

    def regions_of(self, username: str) -> list[str] | None:
        return self._query(f"select region from {self.table} where username = %s order by 1", (username,))
