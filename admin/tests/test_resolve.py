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


def test_the_sql_lab_is_for_admins_and_those_granted_lab_on_any_dataset():
    from access_resolve import lab_allowed
    view = {**grant("sales", "user", "ayse"), "permission": "view"}
    lab = {**grant("sales", "group", "Analysts"), "permission": "lab"}
    role_lab = {**grant("inv", "role", "purchasing"), "permission": "lab"}
    assert lab_allowed([], "root", "admin", []) is True
    assert lab_allowed([view, lab], "ayse", "manager", []) is False, "view alone does not open the lab"
    assert lab_allowed([view, lab], "ayse", "manager", ["Analysts"]) is True
    assert lab_allowed([lab], "bob", "manager", ["Other"]) is False
    assert lab_allowed([role_lab], "buyer", "purchasing", []) is True and lab_allowed([role_lab], "ayse", "manager", []) is False
    assert lab_allowed([{**grant("x", "user", "ayse")}], "ayse", "manager", []) is False, "a grant without a permission is a view"


def test_a_viewer_never_has_the_lab_whatever_is_granted():
    from access_resolve import lab_allowed
    g = [{**grant("sales", "role", "viewer"), "permission": "lab"}, {**grant("sales", "user", "vera"), "permission": "lab"}]
    assert lab_allowed(g, "vera", "viewer", []) is False


def test_a_single_field_in_a_dataset_needs_a_grant_even_when_its_cube_is_open():
    from access_resolve import blocked_members
    profit = {"id": "profit", "cubes": [], "members": ["internet_sales.gross_profit", "reseller_sales.gross_profit"]}
    sales = {"id": "sales", "cubes": ["internet_sales"], "members": []}
    ds = [profit, sales]
    assert blocked_members(ds, [], "ayse", "manager", []) == ["internet_sales.gross_profit", "reseller_sales.gross_profit"]
    assert blocked_members(ds, [grant("profit", "group", "Finance")], "ayse", "manager", ["Finance"]) == []
    assert blocked_members(ds, [grant("sales", "user", "ayse")], "ayse", "manager", []) == ["internet_sales.gross_profit", "reseller_sales.gross_profit"], "a grant on the cube's dataset does not open its governed fields"
    assert blocked_members(ds, [], "root", "admin", []) == [] and blocked_members([sales], [], "ayse", "rep", []) == []
    assert blocked_cubes(ds, [], "ayse", "manager", []) == ["internet_sales"], "a dataset with only fields governs no cube"
