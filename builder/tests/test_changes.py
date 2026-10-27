"""What changed between two versions of a saved dashboard: the facts the page words, and that the service attaches them to each version."""
import pathlib

import yaml

from builder import changes

REPO = pathlib.Path(__file__).resolve().parents[2]
BASE = (REPO / "dashboards" / "regional-sales.yml").read_text()


def edited(**changes_):
    spec = yaml.safe_load(BASE)
    for k, v in changes_.items():
        spec[k] = v
    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)


def kinds(out):
    return [c["kind"] for c in out]


def test_the_first_version_is_created_and_an_identical_one_is_unknown():
    assert changes.describe(None, BASE) == [{"kind": "created"}]
    assert changes.describe(BASE, BASE) == [{"kind": "unknown"}], "nothing changed: not an empty list the page would draw as nothing"


def test_a_new_title_and_the_dashboards_own_fields():
    out = changes.describe(BASE, edited(title="Board pack", description="For the board", currency="TRY"))
    assert out[0] == {"kind": "title", "from": yaml.safe_load(BASE)["title"], "to": "Board pack"}
    assert out[1]["kind"] == "page" and set(out[1]["fields"]) == {"description", "currency"}


def test_panels_added_removed_and_changed_are_named_with_their_titles_and_changed_fields():
    spec = yaml.safe_load(BASE)
    panels = spec["panels"]
    spec2 = yaml.safe_load(BASE)
    spec2["panels"] = panels[1:] + [{"id": "note", "type": "text", "markdown": "hello"}]
    spec2["layout"] = [[{"note": 12}]] + [[{p["id"]: 12}] for p in spec2["panels"][:-1]]
    out = changes.describe(BASE, yaml.safe_dump(spec2, sort_keys=False))
    assert {"kind": "panel_added", "id": "note", "title": "note", "type": "text"} in out
    assert any(c["kind"] == "panel_removed" and c["id"] == panels[0]["id"] for c in out)
    assert "layout" in kinds(out)
    spec3 = yaml.safe_load(BASE)
    spec3["panels"][1]["title"] = "Renamed panel"
    spec3["panels"][1]["limit"] = 7
    out3 = changes.describe(BASE, yaml.safe_dump(spec3, sort_keys=False))
    changed = [c for c in out3 if c["kind"] == "panel_changed"]
    assert len(changed) == 1 and changed[0]["title"] == "Renamed panel" and {"title", "limit"} <= set(changed[0]["fields"]), out3


def test_filters_added_removed_and_changed():
    spec = yaml.safe_load(BASE)
    spec["filters"] = [*spec.get("filters", []), {"id": "colour", "dimension": "products.color", "label": "Colour"}]
    out = changes.describe(BASE, yaml.safe_dump(spec, sort_keys=False))
    assert {"kind": "filter_added", "id": "colour", "label": "Colour"} in out
    back = changes.describe(yaml.safe_dump(spec, sort_keys=False), BASE)
    assert {"kind": "filter_removed", "id": "colour", "label": "Colour"} in back
    renamed = yaml.safe_load(yaml.safe_dump(spec))
    renamed["filters"][-1]["label"] = "Color"
    relabel = changes.describe(yaml.safe_dump(spec, sort_keys=False), yaml.safe_dump(renamed, sort_keys=False))
    assert relabel == [{"kind": "filter_changed", "id": "colour", "label": "Color", "fields": ["label"]}]


def test_a_broken_file_and_a_long_list_are_handled():
    assert changes.describe("a: [", BASE) == [{"kind": "unknown"}]
    spec = yaml.safe_load(BASE)
    spec["panels"] = [{"id": f"p{i}", "type": "text", "markdown": "x"} for i in range(40)]
    assert len(changes.describe(BASE, yaml.safe_dump(spec, sort_keys=False))) == changes.MAX_CHANGES
