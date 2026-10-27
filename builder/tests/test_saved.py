"""Saved dashboards: the store contract (in memory, and in Postgres when BUILDER_TEST_PG_DSN points at one) and the rules of who may do what."""
import os
import pathlib

import pytest
import yaml
from dashspec import catalog as cat

from builder import saved
from builder.store import KEEP_VERSIONS, Limit, MemoryStore, NotFound, PgStore

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = cat.from_model(REPO / "cube" / "model")
GOOD = (REPO / "dashboards" / "regional-sales.yml").read_text()           # no profit: every sales role can open it
PROFIT = (REPO / "dashboards" / "sales-overview.yml").read_text()          # has profit: not for a rep
PG = os.environ.get("BUILDER_TEST_PG_DSN")


def make_store(kind):
    if kind == "memory":
        return MemoryStore()
    store = PgStore(**dict(part.split("=", 1) for part in PG.split()))                       # "host=... port=... dbname=... user=builder_app password=..."
    with store._conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM builder.saved_dashboards")
    return store


@pytest.fixture(params=["memory", pytest.param("pg", marks=pytest.mark.skipif(not PG, reason="BUILDER_TEST_PG_DSN is not set"))])
def store(request):
    st = make_store(request.param)
    yield st
    if request.param == "pg":
        with st._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM builder.saved_dashboards")


def who(name="alice", role="manager"):
    return saved.Who(name=name, role=role)


def new(store, owner=None, yaml_text=GOOD, **kw):
    return saved.save_new(store, CATALOG, owner or who(), yaml_text, **kw)


# ------------------------------------------------------------------------------------------------------------------ the store
def test_the_store_creates_reads_lists_updates_and_deletes(store):
    row = store.create(owner="alice", owner_role="manager", title="T", description="D", yaml="a: 1", visibility="private", shared_roles=[], max_saved=5)
    assert row["version"] == 1 and row["owner"] == "alice" and store.get(row["id"])["yaml"] == "a: 1" and [r["id"] for r in store.list(owner="alice")] == [row["id"]]
    assert store.list(owner="bob") == []
    up = store.update(row["id"], by="alice", yaml="a: 2", title="T2", visibility="roles", shared_roles=["rep"])
    assert (up["version"], up["title"], up["visibility"], up["shared_roles"]) == (2, "T2", "roles", ["rep"])
    same = store.update(row["id"], by="alice", yaml="a: 2")
    assert same["version"] == 2, "an unchanged YAML is not a new version"
    assert [v["version"] for v in store.list_versions(row["id"])] == [2, 1] and store.get_version(row["id"], 1)["yaml"] == "a: 1"
    store.delete(row["id"])
    assert store.get(row["id"]) is None and store.list_versions(row["id"]) == []
    with pytest.raises(NotFound):
        store.delete(row["id"])
    with pytest.raises(NotFound):
        store.update(row["id"], by="alice", title="x")


def test_the_store_keeps_the_last_versions_and_enforces_the_limit(store):
    row = store.create(owner="alice", owner_role="manager", title="T", description="", yaml="v: 1", visibility="private", shared_roles=[], max_saved=2)
    for n in range(2, KEEP_VERSIONS + 5):
        store.update(row["id"], by="alice", yaml=f"v: {n}")
    versions = [v["version"] for v in store.list_versions(row["id"])]
    assert len(versions) == KEEP_VERSIONS and versions[0] == KEEP_VERSIONS + 4 and 1 not in versions
    store.create(owner="alice", owner_role="manager", title="U", description="", yaml="b: 1", visibility="private", shared_roles=[], max_saved=2)
    with pytest.raises(Limit):
        store.create(owner="alice", owner_role="manager", title="V", description="", yaml="c: 1", visibility="private", shared_roles=[], max_saved=2)
    store.create(owner="bob", owner_role="manager", title="W", description="", yaml="d: 1", visibility="private", shared_roles=[], max_saved=2)


# ------------------------------------------------------------------------------------------------------------------ the rules
def test_a_saved_dashboard_is_private_until_it_is_shared(store):
    d = new(store, title="My sales")
    assert d["visibility"] == "private" and d["title"] == "My sales" and d["mine"] and d["readable_by"] and "rep" in d["readable_by"]
    assert [x["id"] for x in saved.list_saved(store, CATALOG, who())] == [d["id"]]
    assert saved.list_saved(store, CATALOG, who("bob", "manager")) == []
    with pytest.raises(saved.SavedError) as e:
        saved.open_saved(store, CATALOG, who("bob", "manager"), d["id"])
    assert e.value.status == 404, "the same answer for 'no such' and 'not yours'"


def test_sharing_with_roles_and_with_everyone(store):
    d = new(store)
    saved.update_saved(store, CATALOG, who(), d["id"], visibility="roles", shared_roles=["rep"])
    assert saved.open_saved(store, CATALOG, who("rita", "rep"), d["id"])["meta"]["owner"] == "alice"
    with pytest.raises(saved.SavedError):
        saved.open_saved(store, CATALOG, who("bob", "manager"), d["id"])
    saved.update_saved(store, CATALOG, who(), d["id"], visibility="everyone")
    assert saved.open_saved(store, CATALOG, who("bob", "manager"), d["id"])["spec"]["id"] == "draft"
    assert saved.open_saved(store, CATALOG, who("bob", "manager"), d["id"])["spec"]["roles"] == ["manager"], "validated and labelled for the opener"
    assert any(x["id"] == d["id"] for x in saved.list_saved(store, CATALOG, who("bob", "manager")))
    saved.update_saved(store, CATALOG, who(), d["id"], visibility="private")
    assert saved.list_saved(store, CATALOG, who("bob", "manager")) == []


def test_a_role_that_cannot_read_the_dashboard_is_told_why_and_nothing_leaks(store):
    d = new(store, yaml_text=PROFIT, visibility="everyone")
    assert "rep" not in d["readable_by"] and "manager" in d["readable_by"]
    listing = saved.list_saved(store, CATALOG, who("rita", "rep"))
    assert listing[0]["readable"] is False and any("rep" in p and "gross_profit" in p for p in listing[0]["problems"])
    with pytest.raises(saved.SavedError) as e:
        saved.open_saved(store, CATALOG, who("rita", "rep"), d["id"])
    assert e.value.status == 422 and any("role 'rep' cannot read 'internet_sales.gross_profit'" in p for p in e.value.problems)
    assert saved.list_saved(store, CATALOG, who("bob", "manager"))[0]["readable"] is True


def test_what_is_saved_must_be_valid_for_the_saver(store):
    for bad, role in ((PROFIT, "rep"), ("not: [valid", "manager"), ("- a", "manager")):
        with pytest.raises(saved.SavedError) as e:
            new(store, who("x", role), yaml_text=bad)
        assert e.value.status == 422
    assert saved.list_saved(store, CATALOG, who("x", "rep")) == []


def test_only_the_owner_changes_the_yaml_and_an_admin_can_unshare_and_delete(store):
    d = new(store, visibility="everyone")
    with pytest.raises(saved.SavedError) as e:
        saved.update_saved(store, CATALOG, who("bob", "manager"), d["id"], yaml_text=GOOD)
    assert e.value.status == 403
    with pytest.raises(saved.SavedError) as e:
        saved.update_saved(store, CATALOG, who("bob", "manager"), d["id"], visibility="private")
    assert e.value.status == 403
    with pytest.raises(saved.SavedError) as e:
        saved.delete_saved(store, who("bob", "manager"), d["id"])
    assert e.value.status == 403
    saved.update_saved(store, CATALOG, who("root", "admin"), d["id"], visibility="private")
    assert store.get(d["id"])["visibility"] == "private"
    assert [x["id"] for x in saved.list_saved(store, CATALOG, who("root", "admin"), everything=True)] == [d["id"]]
    assert saved.open_saved(store, CATALOG, who("root", "admin"), d["id"])["meta"]["owner"] == "alice", "an admin can open any dashboard"
    saved.delete_saved(store, who("root", "admin"), d["id"])
    assert store.get(d["id"]) is None


def test_versions_are_the_owners_and_can_be_restored(store):
    d = new(store, title="v1")
    spec = yaml.safe_load(GOOD)
    spec["title"] = "Second"
    saved.update_saved(store, CATALOG, who(), d["id"], yaml_text=yaml.safe_dump(spec))
    assert [v["version"] for v in saved.versions(store, who(), d["id"])] == [2, 1]
    assert saved.open_saved(store, CATALOG, who(), d["id"])["spec"]["title"] == "Second"
    assert saved.open_saved(store, CATALOG, who(), d["id"], version=1)["spec"]["title"] == "Regional sales"
    back = saved.restore(store, CATALOG, who(), d["id"], 1)
    assert back["version"] == 3 and saved.open_saved(store, CATALOG, who(), d["id"])["spec"]["title"] == "Regional sales"
    saved.update_saved(store, CATALOG, who(), d["id"], visibility="everyone")
    for fn in (lambda: saved.versions(store, who("bob", "manager"), d["id"]), lambda: saved.open_saved(store, CATALOG, who("bob", "manager"), d["id"], version=1),
               lambda: saved.restore(store, CATALOG, who("bob", "manager"), d["id"], 1)):
        with pytest.raises(saved.SavedError) as e:
            fn()
        assert e.value.status == 403
    with pytest.raises(saved.SavedError) as e:
        saved.open_saved(store, CATALOG, who(), d["id"], version=99)
    assert e.value.status == 404


def test_sharing_input_is_checked(store):
    d = new(store)
    for kw in ({"visibility": "world"}, {"visibility": "roles", "shared_roles": []}, {"visibility": "roles", "shared_roles": ["boss"]}):
        with pytest.raises(saved.SavedError) as e:
            saved.update_saved(store, CATALOG, who(), d["id"], **kw)
        assert e.value.status == 422
    with pytest.raises(saved.SavedError):
        new(store, visibility="roles", shared_roles=[])
    with pytest.raises(saved.SavedError) as e:
        new(store, max_saved=0)
    assert e.value.status == 409 and "delete one first" in e.value.message


def test_the_title_comes_from_the_spec_and_can_be_overridden_and_trimmed(store):
    assert new(store)["title"] == "Regional sales"
    assert new(store, title="  Mine  ")["title"] == "Mine"
    assert len(new(store, title="x" * 400)["title"]) == 120


# ------------------------------------------------------------------------------------------------------------------ tags
def listed(store, who_, **kw):
    return {d["title"]: d for d in saved.list_saved(store, CATALOG, who_, **kw)}


def test_the_list_carries_the_tags_of_the_yaml_for_your_own_and_for_shared_dashboards(store):
    new(store, who("alice"), title="Mine")
    new(store, who("alice"), title="Everyone's", visibility="everyone")
    assert listed(store, who("alice"))["Mine"]["tags"] == ["sales", "regional"]
    assert listed(store, who("bob"))["Everyone's"]["tags"] == ["sales", "regional"]
    assert "Mine" not in listed(store, who("bob")), "tags do not make a private dashboard visible"


def test_a_dashboard_your_role_cannot_open_still_shows_its_tags(store):
    new(store, who("alice", "manager"), yaml_text=PROFIT, title="Profit", visibility="everyone")
    row = listed(store, who("rep1", "rep"))["Profit"]
    assert row["readable"] is False and row["tags"] == ["sales"]


def test_a_new_version_shows_its_new_tags_and_a_yaml_without_tags_has_none(store):
    row = new(store, who("alice"), title="T")
    assert listed(store, who("alice"))["T"]["tags"] == ["sales", "regional"]
    retagged = GOOD.replace("tags: [sales, regional]", "tags: [management]")
    saved.update_saved(store, CATALOG, who("alice"), row["id"], yaml_text=retagged)
    assert listed(store, who("alice"))["T"]["tags"] == ["management"], "the cache is keyed by version"
    untagged = GOOD.replace("tags: [sales, regional]\n", "")
    saved.update_saved(store, CATALOG, who("alice"), row["id"], yaml_text=untagged)
    assert listed(store, who("alice"))["T"]["tags"] == []


@pytest.mark.parametrize("text,want", [
    ("tags: nope\n", []), ("tags: [1, ok, '', null]\n", ["ok"]), ("tags: {a: b}\n", []), (": : :\n  - [", []), ("- just\n- a list\n", []), ("", []),
    ("tags: [a, b, c, d, e, f, g]\n", ["a", "b", "c", "d", "e"]), ("tags: [" + "x" * 30 + ", fine]\n", ["fine"]),
])
def test_odd_yaml_never_breaks_a_list_it_just_has_fewer_tags(text, want):
    row = {"id": "odd", "version": 1, "yaml": text}
    assert saved.tags_of(row) == want
    saved._tags.pop(("odd", 1), None)


def test_what_comes_back_cannot_change_the_cache():
    row = {"id": "c", "version": 1, "yaml": "tags: [a]\n"}
    saved.tags_of(row).append("changed")
    assert saved.tags_of(row) == ["a"]
    saved._tags.pop(("c", 1), None)


def test_tags_survive_the_builder_checks_and_the_guide_explains_them():
    from builder import core
    built, problems = core.check_submission(GOOD, CATALOG, "rep")
    assert built is not None and built["spec"]["tags"] == ["sales", "regional"] and "tags:" in built["yaml"], problems
    assert "tags?" in core.SPEC_GUIDE and "ONLY when the request names a topic" in core.SPEC_GUIDE


# ------------------------------------------------------------------------------------------------------------------ the Tags field of the Save dialog
def keys_of(text):
    return list(yaml.safe_load(text))


def test_saving_with_tags_writes_them_into_the_dashboard_after_its_description(store):
    row = new(store, tags=["management", "satış"])
    assert row["tags"] == ["management", "satış"]
    text = store.get(row["id"])["yaml"]
    assert yaml.safe_load(text)["tags"] == ["management", "satış"]
    assert keys_of(text).index("tags") == keys_of(text).index("description") + 1


def test_no_tags_argument_keeps_what_the_yaml_has_and_an_empty_list_removes_them(store):
    assert new(store, title="A")["tags"] == ["sales", "regional"]
    gone = new(store, title="B", tags=[])
    assert gone["tags"] == [] and "tags" not in yaml.safe_load(store.get(gone["id"])["yaml"])


def test_bad_tags_are_refused_with_the_validators_message_before_anything_is_stored(store):
    with pytest.raises(saved.SavedError) as e:
        new(store, tags=["Sales", "ok"])
    assert e.value.status == 422 and e.value.message == "Those tags are not valid."
    assert any("tags[0]: 'Sales' is not lower case; write 'sales'" in p for p in e.value.problems)
    with pytest.raises(saved.SavedError) as e:
        new(store, tags=["a", "b", "c", "d", "e", "f"])
    assert e.value.message == "Those tags are not valid." and any("tags" in p and "too long" in p for p in e.value.problems)
    assert store.list() == [], "nothing was saved"


def test_another_problem_keeps_the_general_message_even_when_tags_are_given(store):
    broken = GOOD.replace("internet_sales.revenue", "internet_sales.nope", 1)
    with pytest.raises(saved.SavedError) as e:
        new(store, yaml_text=broken, tags=["fine"])
    assert e.value.message == "The dashboard is not valid for your role." and any("nope" in p for p in e.value.problems)


def test_changing_only_the_tags_makes_a_new_version_and_the_same_tags_do_not(store):
    row = new(store, who("alice"))
    same = saved.update_saved(store, CATALOG, who("alice"), row["id"], tags=["sales", "regional"])
    assert same["version"] == 1, "asking for the tags it already has is not a change"
    changed = saved.update_saved(store, CATALOG, who("alice"), row["id"], tags=["management"])
    assert changed["version"] == 2 and changed["tags"] == ["management"]
    assert yaml.safe_load(store.get(row["id"])["yaml"])["tags"] == ["management"]
    assert yaml.safe_load(store.get_version(row["id"], 1)["yaml"])["tags"] == ["sales", "regional"], "the old version keeps its tags"
    removed = saved.update_saved(store, CATALOG, who("alice"), row["id"], tags=[])
    assert removed["version"] == 3 and removed["tags"] == []
    assert saved.update_saved(store, CATALOG, who("alice"), row["id"], tags=[])["version"] == 3


def test_only_the_owner_changes_tags_not_even_an_admin_nor_someone_it_is_shared_with(store):
    row = new(store, who("alice"), visibility="everyone")
    for other in (who("bob"), who("root", "admin")):
        with pytest.raises(saved.SavedError) as e:
            saved.update_saved(store, CATALOG, other, row["id"], tags=["mine-now"])
        assert e.value.status == 403, other
    assert saved.update_saved(store, CATALOG, who("alice"), row["id"], title="Renamed")["tags"] == ["sales", "regional"], "renaming leaves the tags alone"


def test_tags_given_with_a_yaml_edit_win_over_the_tags_in_that_yaml(store):
    row = new(store, who("alice"))
    edited = GOOD.replace("tags: [sales, regional]", "tags: [fromyaml]")
    up = saved.update_saved(store, CATALOG, who("alice"), row["id"], yaml_text=edited, tags=["fromfield"])
    assert up["tags"] == ["fromfield"]
    up = saved.update_saved(store, CATALOG, who("alice"), row["id"], yaml_text=edited)
    assert up["tags"] == ["fromyaml"], "without the field the YAML's own tags are used"


def test_retag_leaves_text_it_cannot_read_to_the_validator_and_places_tags_sensibly():
    assert saved.retag("- a list\n- not a mapping\n", ["x"]) == "- a list\n- not a mapping\n"
    assert saved.retag(": : :\n  - [", ["x"]) == ": : :\n  - ["
    no_description = "spec: 1\ntitle: T\nlocale: en-US\n"
    assert keys_of(saved.retag(no_description, ["x"])) == ["spec", "title", "tags", "locale"], "after the title when there is no description"
    assert keys_of(saved.retag("spec: 1\n", ["x"])) == ["spec", "tags"], "at the end when there is neither"
    same = "spec: 1\ntitle: T\nlocale: en-US\ntags: [x]\n"
    assert saved.retag(same, ["x"]) == same, "the same tags: the text is untouched, even in another position"
    assert "tags" not in yaml.safe_load(saved.retag(same, []))
