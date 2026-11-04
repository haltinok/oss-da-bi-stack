"""The row-level dimension registry: the default file (cube/rls_dimensions.json) against the Cube model, since a dimension Cube could not filter on must fail the build,
not silently leave rows open; and the registry the services read from the database at startup (rls_registry.py, cube/rls_registry.js)."""
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from dashspec import catalog as cat

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "auth"))
sys.path.insert(0, str(REPO / "scripts"))
import rls_dimensions_sql  # noqa: E402  (scripts/, auth/ are not packages)
import rls_registry as R  # noqa: E402
DIMS = json.loads((REPO / "cube" / "rls_dimensions.json").read_text(encoding="utf-8"))["dimensions"]
CATALOG = cat.from_model(REPO / "cube" / "model")


def test_every_dimension_is_well_formed_and_unique():
    ids = [d["id"] for d in DIMS]
    assert len(ids) == len(set(ids)) and all(__import__("re").fullmatch(r"[a-z][a-z0-9_]{0,39}", i) for i in ids)
    for d in DIMS:
        assert d["when_empty"] in ("deny", "allow") and d["cubes"] and d["values"]["kind"] in ("seed_regions", "list", "cube"), d["id"]
        assert d["labels"]["en"], d["id"]


def test_each_dimension_member_exists_and_is_reachable_from_every_cube_it_filters():
    for d in DIMS:
        cube, member = d["member"].split(".")
        assert cube in CATALOG.cubes and member in CATALOG.cubes[cube]["dimensions"], f"{d['id']}: {d['member']} is not a dimension in the model"
        for c in d["cubes"]:
            assert c in CATALOG.cubes, f"{d['id']}: no cube {c}"
            assert c == cube or cube in (CATALOG.cubes[c]["joins"] or ()), f"{d['id']}: {c} does not join {cube}, so a filter on {d['member']} would not be valid for it"


def test_the_copies_the_services_read_are_identical():
    text = (REPO / "cube" / "rls_dimensions.json").read_text()
    for svc in ("auth", "admin"):
        assert (REPO / svc / "rls_dimensions.json").read_text() == text, f"{svc}/rls_dimensions.json differs from cube/rls_dimensions.json"


# ---- the registry in the database (PLAN-rls-registry-db.md)


def test_the_seed_sql_is_generated_from_the_default_file():
    assert (REPO / "postgres" / "init" / "10_rls_dimensions.sql").read_text(encoding="utf-8") == rls_dimensions_sql.render(DIMS), \
        "postgres/init/10_rls_dimensions.sql is out of date: run python3 scripts/rls_dimensions_sql.py"
    assert "ON CONFLICT (id) DO NOTHING" in rls_dimensions_sql.render(DIMS), "the seed never overwrites a dimension changed in the database"


def test_the_seed_quotes_its_text():
    sql = rls_dimensions_sql.render([{"id": "x", "member": "a.b", "cubes": ["a"], "when_empty": "allow", "values": {"kind": "list", "values": ["O'Brien"]},
                                      "labels": {"en": "It's"}, "empty_message": "none'; drop table x; --"}])
    assert "O''Brien" in sql and "It''s" in sql and "'none''; drop table x; --'" in sql


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.clear(), "no dimensions"),
    (lambda d: d[0].update(when_empty="maybe"), "when_empty"),
    (lambda d: d[0].update(member="region"), "cube.field"),
    (lambda d: d[0].update(cubes=[]), "cubes"),
    (lambda d: d[1].update(id=d[0]["id"]), "used twice"),
    (lambda d: d[1].update(values={"kind": "list", "values": []}), "values list"),
    (lambda d: d[0].update(values={"kind": "sql"}), "values.kind"),
    (lambda d: d[0].update(seed="yes"), "seed"),
    (lambda d: d[0].update(labels={"en": 5}), "labels"),
    (lambda d: d[0].update(id="Territory"), "id must be"),
])
def test_a_registry_the_services_could_not_enforce_is_refused(mutate, needle):
    dims = json.loads(json.dumps(DIMS))
    mutate(dims)
    with pytest.raises(R.RegistryError, match=needle):
        R.normalize(dims)


def test_missing_fields_get_their_defaults_and_a_row_reads_like_the_file():
    assert R.normalize([{"id": "x", "member": "a.b", "cubes": ["a"], "when_empty": "allow"}]) == \
        [{"id": "x", "member": "a.b", "cubes": ["a"], "when_empty": "allow", "values": {"kind": "cube"}, "seed": False, "labels": {}, "empty_message": ""}]
    d = DIMS[0]
    row = (d["id"], d["member"], d["cubes"], d["when_empty"], d["values"], d.get("seed", False), d.get("labels", {}), d.get("empty_message", ""))
    assert R.normalize([R.from_row(row)]) == R.normalize([d])
    assert R.normalize([R.from_row(dict(zip(("id", "member", "cubes", "when_empty", "values_source", "seed", "labels", "empty_message"), row, strict=True)))]) == R.normalize([d])


class FakeConn:
    def __init__(self, rows, fail=0):
        self.rows, self.fail = rows, fail

    def cursor(self):
        conn = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql):
                assert sql == R.SELECT

            def fetchall(self):
                return conn.rows
        return Cur()

    def close(self):
        pass


def test_reading_the_database_retries_until_it_answers_then_validates():
    attempts = []
    rows = [(d["id"], d["member"], d["cubes"], d["when_empty"], d["values"], d.get("seed", False), d.get("labels", {}), d.get("empty_message", "")) for d in DIMS]

    def connect():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("connection refused")
        return FakeConn(rows)
    dims = R.from_db(connect, wait=5, pause=0, log=lambda *_: None)
    assert len(attempts) == 3 and dims == R.normalize(DIMS)


def test_a_database_that_never_answers_or_holds_no_rows_stops_the_service():
    def down():
        raise OSError("connection refused")
    with pytest.raises(RuntimeError, match="cannot read access.rls_dimension"):
        R.from_db(down, wait=0, pause=0, log=lambda *_: None)
    with pytest.raises(R.RegistryError, match="no dimensions"):
        R.from_db(lambda: FakeConn([]), wait=0, pause=0, log=lambda *_: None)


def test_without_a_database_the_default_file_is_the_registry():
    dims, source = R.load(None, path=REPO / "cube" / "rls_dimensions.json", log=lambda *_: None)
    assert source == "file" and dims == R.normalize(DIMS)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_python_and_cube_compute_the_same_version():
    """The auth service puts the Python version in the token and Cube compares it with its own: they must agree on the same list, Unicode labels included."""
    extra = [*DIMS, {"id": "x", "member": "a.b", "cubes": ["a"], "when_empty": "allow", "labels": {"tr": "Şube \"ana\" \\  "}, "empty_message": "ç"}]
    script = ("const r = require(process.argv[1]); let s = ''; process.stdin.on('data', (c) => s += c).on('end', () => "
              "console.log(JSON.stringify(JSON.parse(s).map((d) => r.version(r.normalize(d))))));")
    out = subprocess.run(["node", "-e", script, str(REPO / "cube" / "rls_registry.js")], input=json.dumps([DIMS, extra]), capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [R.version(R.normalize(DIMS)), R.version(R.normalize(extra))]
