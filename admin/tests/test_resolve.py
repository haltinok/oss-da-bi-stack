"""Which cubes datasets keep from a person (access_resolve.blocked_cubes), and that auth/, builder/ and admin/ ship the very same file."""
import pathlib

from access_resolve import blocked_cubes

ROOT = pathlib.Path(__file__).resolve().parents[2]
SALES = {"id": "sales", "cubes": ["internet_sales", "reseller_sales"]}
INV = {"id": "inv", "cubes": ["inventory_health"]}


def grant(dataset, type_, principal):
    return {"object_id": dataset, "principal_type": type_, "principal": principal}


def test_without_datasets_nothing_is_blocked():
    assert blocked_cubes([], [], "ayse", "manager", []) == []


def test_a_governed_cube_is_blocked_without_a_grant_and_open_with_one_to_the_person_a_group_or_the_role():
    ds = [SALES, INV]
    assert blocked_cubes(ds, [], "ayse", "manager", ["Ops"]) == ["internet_sales", "inventory_health", "reseller_sales"]
    assert blocked_cubes(ds, [grant("sales", "user", "ayse")], "ayse", "manager", []) == ["inventory_health"]
    assert blocked_cubes(ds, [grant("sales", "group", "Ops")], "ayse", "manager", ["Ops"]) == ["inventory_health"]
    assert blocked_cubes(ds, [grant("sales", "role", "manager")], "ayse", "manager", []) == ["inventory_health"]
    assert blocked_cubes(ds, [grant("sales", "role", "manager"), grant("inv", "user", "ayse")], "ayse", "manager", []) == []


def test_a_grant_to_somebody_else_does_not_count():
    ds = [SALES]
    assert blocked_cubes(ds, [grant("sales", "user", "bob"), grant("sales", "group", "Other"), grant("sales", "role", "rep")], "ayse", "manager", ["Ops"]) == ["internet_sales", "reseller_sales"]


def test_a_cube_in_two_datasets_opens_with_either_grant():
    ds = [SALES, {"id": "all", "cubes": ["internet_sales"]}]
    assert blocked_cubes(ds, [grant("all", "user", "ayse")], "ayse", "rep", []) == ["reseller_sales"]


def test_admins_are_never_blocked():
    assert blocked_cubes([SALES, INV], [], "root", "admin", []) == []


def test_the_three_services_ship_the_same_resolution_file():
    one = (ROOT / "auth" / "access_resolve.py").read_bytes()
    assert (ROOT / "builder" / "access_resolve.py").read_bytes() == one and (ROOT / "admin" / "access_resolve.py").read_bytes() == one
