"""The row-level dimension registry (PLAN-rls-registry-db.md): which field each row rule limits, on which cubes, and whether no value denies or allows.

It lives in Postgres, `access.rls_dimension`, and a service reads it once, when it starts. Without an access-database login the default file
(rls_dimensions.json, next to this module) is used instead. A registry that cannot be read, or is not valid, stops the service: it never runs on half a list.

Identical copies: auth/rls_registry.py and admin/rls_registry.py (admin/tests/test_resolve.py checks). cube/cube.js has a JavaScript mirror of
`normalize` and `version`; dashboards/tests/test_rls_dimensions.py checks both give the same version.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import time

ID = re.compile(r"[a-z][a-z0-9_]{0,39}")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MEMBER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*")
VALUE_KINDS = ("seed_regions", "list", "cube")
SELECT = ("select id, member, cubes, when_empty, values_source, seed, labels, empty_message "
          "from access.rls_dimension order by position, id")


class RegistryError(ValueError):
    """The rows are not a registry a service may enforce."""


def normalize(dims: list) -> list[dict]:
    """The registry in its canonical form (every field present, in a fixed shape), or RegistryError naming the first problem."""
    if not isinstance(dims, list) or not dims:
        raise RegistryError("the registry has no dimensions (an empty list would leave every row open)")
    out, seen = [], set()
    for i, d in enumerate(dims):
        where = f"dimension {i + 1}"
        if not isinstance(d, dict):
            raise RegistryError(f"{where}: not an object")
        id_ = d.get("id")
        if not isinstance(id_, str) or not ID.fullmatch(id_):
            raise RegistryError(f"{where}: id must be lower-case letters, digits and _ (got {id_!r})")
        where = f"dimension '{id_}'"
        if id_ in seen:
            raise RegistryError(f"{where}: the id is used twice")
        seen.add(id_)
        member = d.get("member")
        if not isinstance(member, str) or not MEMBER.fullmatch(member):
            raise RegistryError(f"{where}: member must be cube.field (got {member!r})")
        cubes = d.get("cubes")
        if not isinstance(cubes, list) or not cubes or not all(isinstance(c, str) and NAME.fullmatch(c) for c in cubes):
            raise RegistryError(f"{where}: cubes must be a non-empty list of cube names")
        when_empty = d.get("when_empty")
        if when_empty not in ("deny", "allow"):
            raise RegistryError(f"{where}: when_empty must be deny or allow (got {when_empty!r})")
        values = d.get("values", {"kind": "cube"})
        if not isinstance(values, dict) or values.get("kind") not in VALUE_KINDS:
            raise RegistryError(f"{where}: values.kind must be one of {', '.join(VALUE_KINDS)}")
        if values["kind"] == "list":
            vals = values.get("values")
            if not isinstance(vals, list) or not vals or not all(isinstance(v, str) for v in vals):
                raise RegistryError(f"{where}: a values list needs at least one value, all text")
            values = {"kind": "list", "values": list(vals)}
        else:
            values = {"kind": values["kind"]}
        seed = d.get("seed", False)
        if not isinstance(seed, bool):
            raise RegistryError(f"{where}: seed must be true or false")
        labels = {} if d.get("labels") is None else d["labels"]
        if not isinstance(labels, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
            raise RegistryError(f"{where}: labels must map a language to a text")
        message = "" if d.get("empty_message") is None else d["empty_message"]
        if not isinstance(message, str):
            raise RegistryError(f"{where}: empty_message must be text")
        out.append({"id": id_, "member": member, "cubes": list(cubes), "when_empty": when_empty, "values": values, "seed": seed,
                    "labels": dict(labels), "empty_message": message})
    return out


def canonical(dims: list[dict]) -> str:
    return json.dumps(dims, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def version(dims: list[dict]) -> str:
    """A short hash of the canonical registry: the auth service puts it in the Cube token and Cube refuses a token from a different registry."""
    return hashlib.sha256(canonical(dims).encode("utf-8")).hexdigest()[:16]


def from_row(r) -> dict:
    """A row of SELECT (a tuple or a dict) as a registry entry."""
    keys = ("id", "member", "cubes", "when_empty", "values_source", "seed", "labels", "empty_message")
    d = dict(r) if isinstance(r, dict) else dict(zip(keys, r, strict=True))
    return {"id": d["id"], "member": d["member"], "cubes": list(d["cubes"] or []), "when_empty": d["when_empty"],
            "values": d["values_source"], "seed": d["seed"], "labels": d["labels"], "empty_message": d["empty_message"]}


def from_file(path: pathlib.Path) -> list[dict]:
    return normalize(json.loads(path.read_text(encoding="utf-8"))["dimensions"])


def from_db(connect, wait: float = 60.0, pause: float = 2.0, log=print) -> list[dict]:
    """Read access.rls_dimension through `connect()` (a DB-API connection). Retries a connection or query error for `wait` seconds (Postgres may
    start after this service); a registry that was read but is not valid fails at once, since retrying would not change it."""
    deadline = time.monotonic() + wait
    while True:
        try:
            conn = connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(SELECT)
                    rows = cur.fetchall()
            finally:
                conn.close()
            break
        except Exception as exc:                                     # noqa: BLE001 (any failure to read is retried, then fatal)
            if time.monotonic() >= deadline:
                raise RuntimeError(f"cannot read access.rls_dimension: {exc}") from exc
            log(f"rls registry: cannot read access.rls_dimension yet ({type(exc).__name__}: {exc}); retrying")
            time.sleep(pause)
    return normalize([from_row(r) for r in rows])


def load(connect=None, path: pathlib.Path | None = None, wait: float = 60.0, log=print) -> tuple[list[dict], str]:
    """(dimensions, source): from the database when `connect` is given, else from the default file. Raises on any failure (the caller stops)."""
    if connect is None:
        path = path or pathlib.Path(__file__).with_name("rls_dimensions.json")
        dims, source = from_file(path), "file"
    else:
        dims, source = from_db(connect, wait=wait, log=log), "database"
    log(f"rls registry: {len(dims)} dimension(s) from the {source} ({', '.join(d['id'] for d in dims)}), version {version(dims)}")
    return dims, source
