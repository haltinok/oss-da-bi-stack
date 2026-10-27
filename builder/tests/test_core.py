"""The builder loop against a scripted model: what it accepts, what it hands back, when it gives up, and what the model is shown."""
import pathlib
from types import SimpleNamespace

import pytest
import yaml
from dashspec import catalog as cat

from builder import core

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = cat.from_model(REPO / "cube" / "model")
GOOD = (REPO / "dashboards" / "regional-sales.yml").read_text()


def block(**kw):
    return SimpleNamespace(**kw, model_dump=lambda kw=kw: dict(kw))


def submit(text, n=[0]):  # noqa: B006
    n[0] += 1
    return block(type="tool_use", id=f"t{n[0]}", name="submit_dashboard", input={"yaml": text, "summary": "A dashboard."})


class Script:
    """A model that answers from a list (each item: the content blocks of one answer, or a (stop_reason, blocks) pair) and records its calls."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})       # the loop keeps appending to its list
        a = self.answers.pop(0)
        stop, content = a if isinstance(a, tuple) else ("tool_use" if any(b.type == "tool_use" for b in a) else "end_turn", a)
        return SimpleNamespace(content=content, stop_reason=stop, usage=SimpleNamespace(input_tokens=100, output_tokens=50))


def run(model, role="manager", prompt="regional sales", **kw):
    return core.run_build(model, CATALOG, role, prompt, **kw)


def test_a_valid_submission_is_accepted_and_compiled():
    out = run(Script([submit(GOOD)]))
    assert out["status"] == "ok" and out["attempts"] == 1
    assert out["spec"]["id"] == "draft" and out["spec"]["layout"][0] == [{"panel": "kpis", "span": 12}]
    assert out["spec"]["members"]["internet_sales.revenue"]["kind"] == "measure"
    assert "id: draft" in out["yaml"] and out["usage"]["turns"] == 1 and out["message"] == "A dashboard."


def test_the_service_sets_id_and_roles_whatever_the_model_wrote():
    spec = yaml.safe_load(GOOD)
    spec.update(id="whatever", roles=["admin"])
    out = run(Script([submit(yaml.safe_dump(spec))]), role="rep")
    assert out["status"] == "ok" and out["spec"]["id"] == "draft" and out["spec"]["roles"] == ["rep"]


def test_problems_go_back_to_the_model_and_a_fixed_file_is_accepted():
    bad = GOOD.replace("internet_sales.revenue", "internet_sales.revenu", 1)
    model = Script([submit(bad)], [submit(GOOD)])
    out = run(model)
    assert out["status"] == "ok" and out["attempts"] == 2 and out["usage"]["turns"] == 2
    feedback = model.calls[1]["messages"][-1]["content"][0]
    assert feedback["is_error"] and "'internet_sales.revenu' is not in the Cube model" in feedback["content"] and "complete file" in feedback["content"]


def test_it_gives_up_after_three_failed_submissions_and_says_why():
    bad = GOOD.replace("internet_sales.revenue", "internet_sales.revenu")
    out = run(Script([submit(bad)], [submit(bad)], [submit(bad)], [submit(GOOD)]))
    assert out["status"] == "failed" and out["attempts"] == 3 and out["spec"] is None
    assert any("not in the Cube model" in p for p in out["problems"]) and "3 tries" in out["message"]


def test_a_role_cannot_get_members_it_may_not_read_whatever_the_model_does():
    spec = yaml.safe_load(GOOD)
    spec["panels"][0]["measures"].append({"member": "internet_sales.gross_profit", "label": "Profit", "format": "money"})
    out = run(Script([submit(yaml.safe_dump(spec))], [submit(yaml.safe_dump(spec))], [submit(yaml.safe_dump(spec))]), role="rep")
    assert out["status"] == "failed" and any("role 'rep' cannot read 'internet_sales.gross_profit'" in p for p in out["problems"])
    assert run(Script([submit(yaml.safe_dump(spec))]), role="manager")["status"] == "ok"


def test_cannot_build_passes_the_reason_on():
    out = run(Script([block(type="tool_use", id="c1", name="cannot_build", input={"reason": "There is no cost-of-returns measure."})]))
    assert out["status"] == "cannot" and out["message"] == "There is no cost-of-returns measure." and out["spec"] is None and out["attempts"] == 0


def test_a_text_only_answer_is_nudged_to_call_a_tool():
    model = Script([block(type="text", text="Sure, here is a dashboard.")], [submit(GOOD)])
    out = run(model)
    assert out["status"] == "ok" and "Call submit_dashboard" in model.calls[1]["messages"][-1]["content"]


def test_a_refusal_or_a_cut_off_answer_is_reported():
    assert "refused" in run(Script(("refusal", [block(type="text", text="no")])))["message"]
    assert "cut off" in run(Script(("max_tokens", [block(type="text", text="..")])))["message"]


def test_it_never_loops_forever_on_a_model_that_only_talks():
    out = run(Script(*[[block(type="text", text="hmm")]] * core.MAX_TURNS))
    assert out["status"] == "failed" and out["usage"]["turns"] == core.MAX_TURNS


def test_a_logo_is_stripped_and_oversized_or_broken_files_are_rejected():
    spec = yaml.safe_load(GOOD)
    spec["theme"] = {"name": "Fairstone", "logo": "https://tracker.example/x.png"}
    out = run(Script([submit(yaml.safe_dump(spec))]))
    assert out["status"] == "ok" and "logo" not in out["spec"]["theme"] and any("logo" in n for n in out["notes"])
    built, problems = core.check_submission("x" * (core.MAX_YAML + 1), CATALOG, "admin")
    assert built is None and "too long" in problems[0]
    assert "not valid YAML" in core.check_submission("a: [unclosed", CATALOG, "admin")[1][0]
    assert core.check_submission("- a\n- b", CATALOG, "admin")[1] == ["the file must be a YAML mapping"]


def test_refining_hands_the_model_the_current_file_and_the_request():
    model = Script([submit(GOOD)])
    run(model, prompt="make the trend a line", current_yaml=GOOD)
    first = model.calls[0]["messages"][0]["content"]
    assert first.startswith("make the trend a line") and "```yaml" in first and "id: regional-sales" in first


def test_the_model_is_shown_only_what_the_role_may_read_with_descriptions():
    def system(role):
        return core.system_blocks(CATALOG, role)[0]["text"]
    rep, mk, admin = system("rep"), system("marketing"), system("admin")
    assert "measure internet_sales.revenue [sum]: Sales amount of the order lines." in rep
    assert "gross_profit" not in rep and "margin_pct" not in rep and "inventory_health" not in rep and "customers" not in rep
    assert "inventory_health.status" in mk and "vendor_name" not in mk and "suggested_order_value" not in mk and "internet_sales" not in mk
    assert "customers.last_name" in admin and "internet_sales.gross_profit" in admin
    assert "fiscal_year" in rep and "named after the year it ends in" in rep
    assert "cannot_build" in rep and "sum:" in rep and "- reseller_sales.revenue" in rep      # the example is composed for this role
    assert core.system_blocks(CATALOG, "rep")[0]["cache_control"] == {"type": "ephemeral"}


def test_the_visible_catalog_drops_joins_to_cubes_a_role_cannot_see():
    rep = core.visible_catalog(CATALOG, "rep")
    assert "customers" not in rep.cubes["internet_sales"]["joins"] and rep.cubes["internet_sales"]["joins"] == {"dates", "products", "territories"}
    assert set(core.visible_catalog(CATALOG, "purchasing").cubes) == {"inventory_health", "products"}


def test_an_unknown_role_is_refused():
    with pytest.raises(ValueError):
        run(Script(), role="boss")


def test_links_in_text_panels_are_removed_from_a_draft():
    spec = yaml.safe_load(GOOD)
    spec["panels"].append({"id": "note", "type": "text", "markdown": "See [the portal](https://evil.example/login) and [mail](mailto:a@b.c) and **bold**."})
    spec["layout"].append([{"note": 12}])
    out = run(Script([submit(yaml.safe_dump(spec))]))
    note = next(p for p in out["spec"]["panels"] if p["id"] == "note")
    assert note["markdown"] == "See the portal and mail and **bold**." and any("Links" in n for n in out["notes"])


# ------------------------------------------------------------------------------------------------------------------ tabs
def tabbed(text=GOOD, split=1):
    spec = yaml.safe_load(text)
    rows = spec.pop("layout")
    spec["tabs"] = [{"id": "overview", "title": "Overview", "layout": rows[:split]}, {"id": "details", "title": "Details", "layout": rows[split:]}]
    return spec


def test_a_tabbed_submission_is_accepted_and_each_tab_is_compiled():
    out = run(Script([submit(yaml.safe_dump(tabbed()))]))
    assert out["status"] == "ok" and out["attempts"] == 1
    spec = out["spec"]
    assert "layout" not in spec and [t["id"] for t in spec["tabs"]] == ["overview", "details"]
    assert spec["tabs"][0]["layout"][0] == [{"panel": "kpis", "span": 12}]
    assert "tabs:" in out["yaml"] and "layout:" in out["yaml"]


def test_a_model_that_places_a_panel_on_two_tabs_is_told_which_tabs_and_fixes_it():
    bad = tabbed()
    bad["tabs"][1]["layout"].append([{"kpis": 12}])
    model = Script([submit(yaml.safe_dump(bad))], [submit(yaml.safe_dump(tabbed()))])
    out = run(model)
    assert out["status"] == "ok" and out["attempts"] == 2
    feedback = model.calls[1]["messages"][-1]["content"][0]["content"]
    assert "tabs: panel 'kpis' is placed 2 times (tab 'overview' and tab 'details'), it must be placed once" in feedback


def test_a_row_that_is_not_12_wide_on_a_tab_names_the_tab():
    bad = tabbed()
    bad["tabs"][1]["layout"][0] = [{"trend": 8}, {"lines": 3}]
    model = Script([submit(yaml.safe_dump(bad))], [submit(yaml.safe_dump(tabbed()))])
    run(model)
    assert "tab 'details': row 1: the widths add up to 11" in model.calls[1]["messages"][-1]["content"][0]["content"]


def test_both_layout_and_tabs_is_sent_back_with_the_one_of_message():
    bad = tabbed()
    bad["layout"] = yaml.safe_load(GOOD)["layout"]
    model = Script([submit(yaml.safe_dump(bad))], [submit(yaml.safe_dump(tabbed()))])
    assert run(model)["status"] == "ok"
    assert "needs exactly one of: layout, tabs" in model.calls[1]["messages"][-1]["content"][0]["content"]


def test_a_role_cannot_get_members_it_may_not_read_on_any_tab():
    spec = tabbed((REPO / "dashboards" / "sales-overview.yml").read_text(), split=2)             # its KPI row has profit: a rep may not read it, on any tab
    out = run(Script([submit(yaml.safe_dump(spec))], [submit(yaml.safe_dump(spec))], [submit(yaml.safe_dump(spec))]), role="rep")
    assert out["status"] == "failed" and any("role 'rep' cannot read" in p for p in out["problems"])


def test_the_model_is_told_when_to_use_tabs_and_shown_how():
    for role in ("admin", "rep", "purchasing"):
        text = core.system_blocks(CATALOG, role)[0]["text"]
        assert "tabs: INSTEAD of layout" in text and "ONLY when the request asks for pages" in text and "about 8 panels" in text
        assert "the same dashboard on two tabs" in text and "id: overview" in text, role
        assert "### A tab (`tabs[]`)" in text and "| `tabs` |" in text, "the generated field reference has it too"


def test_the_tabs_example_shown_to_the_model_validates_for_every_role():
    for role in core.ROLES:
        visible = core.visible_catalog(CATALOG, role)
        text = core.example_spec(visible, role)
        if "the same dashboard on two tabs" not in text:
            continue
        first = text.split("\n---\n")[0]
        head, tail = first.split("# the same dashboard on two tabs")
        spec = yaml.safe_load(head)
        spec.pop("layout")
        spec.update(yaml.safe_load(tail.split("\n", 1)[1]))
        built, problems = core.check_submission(yaml.safe_dump(spec, allow_unicode=True), CATALOG, role)
        assert built is not None and len(built["spec"]["tabs"]) == 2, (role, problems)
