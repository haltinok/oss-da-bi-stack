"""The dashboard builder: a prompt becomes a validated dashboard spec.

A model (Claude, or the rule-based stand-in in standin.py, behind the same `client.messages.create` interface the proposal agent uses) is
given the member catalog the signed-in role may read and the spec format, and answers by calling `submit_dashboard` with YAML or
`cannot_build` with a reason. The harness checks every submission with dashspec (schema, members, joins, click rules and the role rules of
Cube) and hands the model the validator's messages to fix, up to MAX_ATTEMPTS times. What comes out is always a spec this role can render:
the model cannot make a page show data the role may not read, because Cube enforces that on every query and the validator refuses members
the role cannot read. The model never sees data rows, only member names and types.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable

import yaml
from dashspec import catalog as cat
from dashspec.compile import compile_spec
from dashspec.validate import ROLE_CUBES, denied, validate

from builder import provider

MODEL = provider.model()                                         # the model of this process (see builder/provider.py for DeepSeek and other compatible servers)
EFFORT = os.environ.get("BUILDER_EFFORT", "medium")              # sent to Anthropic only; empty sends nothing
SPEC_REFERENCE = os.environ.get("BUILDER_SPEC_REFERENCE", "1") not in ("0", "", "false")
MAX_ATTEMPTS = int(os.environ.get("BUILDER_MAX_ATTEMPTS", "3"))   # failed submissions before giving up
MAX_TURNS = MAX_ATTEMPTS + 3                                       # plus the turns that only talk
MAX_TOKENS = 8000
MAX_PROMPT = 2000
MAX_YAML = 30_000
LINK = re.compile(r"\[([^\]]*)\]\(\s*[a-zA-Z][a-zA-Z0-9+.-]*:[^)]*\)")      # [text](scheme:...) -> text
ROLES = ("admin", "manager", "rep", "purchasing", "marketing")

SPEC_GUIDE = """\
A dashboard is one YAML file. Top level: spec: 1, id, title, description, tags?, locale (en-US | tr-TR), currency (USD | TRY), time, filters, panels, layout.
tags: 0-5 short lower-case words (letters, digits, spaces, hyphens; 24 characters at most) for finding and grouping on the list page: write them ONLY when the request names a topic or group ("a sales dashboard for management"), 1-3 words, in the dashboard's language, most important first; never anything sensitive.
Do not write roles, theme.logo or id: the service sets them.

time: { dimension: <a time dimension>, fiscal_year_start: 7 }
filters: list of { id, dimension, label, parent? }  (selects above the panels; every panel applies them unless it lists the id in ignore_filters)
panels: list of { id, type, title?, ignore_filters?, ... }, types:
  kpi        measures: [ {member|sum|ratio, label, format} ... max 8 ], sparkline: { granularity: month }
  timeseries series: [ {member|sum|ratio, label, color?, format} ], granularity, style: line | area | stacked-area | bar | stacked-bar,
             and EITHER granularities?: [month, quarter, year] (a switch) + on_click?: { set_filter: <id of a fiscal_year filter> }
             OR drill: [year, month, day] (a drill-down: a click opens the next finer level for that period and filters every other panel to it; granularity = the first level; no on_click)
  bar        measure: <m> (+ label)  OR  stack: [ {member, label, color?} x2+ ]   by: <dimension>, by_label, sort, limit, orientation?: horizontal | vertical, format, on_click?: { set_filter: <filter on the by dimension> }
  pie        measure: <m> OR sum: [a.m, b.m] (needs label), label, by: <dimension>, by_label, limit (slices before "Other", 2-30), style: pie | donut, format, on_click?: { set_filter: <filter on the by dimension> }
  treemap    measure, group: [dim] or [dim, dim], format, on_click?: { set_filter: [<filter on group[0]>, <filter on group[1]>] }
  table      columns: [ member | {member, label, format} ], order: { member: asc|desc }, limit, totals?: footer | header (a bold total row over all matching rows; needs a measure column), on_click?
  pivot      rows: [dim] or [dim, dim] (down the side; two = the first groups the second), columns: <one other dimension> OR { member: <time dimension>, granularity: month|quarter|year|... } (across the top; use the second for "by month"), measures: [ member | {member, label, format} ] (1-3),
             totals?: both | rows | columns | none, order?: { by: total | label, dir }, limit?: { rows (25), columns (12) }, heat?: { measure: <one of the measures> } (shades the cells; good for month x region), show?: value | share_of_row | share_of_column | share_of_total (cells as percentages; needs the matching totals, and sum/count measures only: never a ratio), on_click?: { set_filter: [<filter on a rows dimension, or on the columns dimension unless it is a time column>] (max 2) }
  text       markdown
A measure is one of: member: cube.measure | sum: [a.m, b.m] (the same measure of two fact cubes, added; needs label) | ratio: { num: [..], den: [..] } (needs label; format pct).
format: money | int | pct (a fraction) | decimal | number.   color: internet | reseller | #rrggbb.
layout: rows of 12 columns, every panel exactly once: - [kpis: 12]  - [trend: 8, lines: 4]
Rules: use only members from the catalog. Cube cannot join two fact cubes in one query, so combine channels with sum/ratio/stack, nothing else:
no other arithmetic. A filter must be on a dimension the panel's measures can join to (else add it to that panel's ignore_filters).
A click rule: bar and pie -> filter on its `by`; treemap -> filters in the order of its group; table -> a dimension column; pivot -> a rows or columns dimension; time chart -> a year filter.
Use a pivot when the request crosses two dimensions ("revenue by category and year", "by region and month"): a bar or a table cannot show a measure against two axes. Use a table for a list, a pivot for a cross-tab.
Write titles and labels in the language of locale: every `label`, including the `label` / `by_label` / `group_labels` of pie, bar and treemap panels (without one the member's English name is shown). If the request needs a metric the catalog does not have, call cannot_build and say which."""

SYSTEM = """You build dashboards for a bank's BI team from a short request. The data is a simulated AdventureWorks company. A person looks at the \
result and can ask for changes; you never see data, only the catalog of members (names and types) the signed-in user may read.

{guide}

Work like this: read the request, choose members from the catalog below, and call submit_dashboard with the YAML. If the checker returns \
problems, fix them and submit again. Never invent a member or approximate a metric the catalog does not have: call cannot_build instead and \
say what is missing. Keep it focused (a KPI row, one or two charts, maybe a table); do not add panels that were not asked for.
When the request changes an existing dashboard, you are given its YAML: submit the complete changed file.

The complete field reference (generated from the schema; every field the file may contain):
{reference}

Complete examples that are valid for this user:
{example}

The catalog (cube, join targets, measures [type], dimensions [type]) for this user:
{catalog}"""

TOOLS = [
    {"name": "submit_dashboard", "description": "Submit the complete dashboard as YAML. It is checked at once; problems come back for you to fix.",
     "input_schema": {"type": "object", "required": ["yaml"], "additionalProperties": False, "properties": {
         "yaml": {"type": "string", "description": "The whole spec file"}, "summary": {"type": "string", "description": "One or two sentences for the user: what the dashboard shows"}}}},
    {"name": "cannot_build", "description": "The request cannot be built with the catalog (a metric or dimension is missing, or it asks for something a dashboard cannot be).",
     "input_schema": {"type": "object", "required": ["reason"], "additionalProperties": False, "properties": {"reason": {"type": "string"}}}},
]


# ------------------------------------------------------------------------------------------------------------------ what a role may see
def visible_catalog(catalog: cat.Catalog, role: str) -> cat.Catalog:
    """The catalog without what Cube would refuse this role (and, for purchasing and marketing, without every cube but their own)."""
    cubes = {}
    for name, c in catalog.cubes.items():
        ms = {m: t for m, t in c["measures"].items() if denied(role, f"{name}.{m}") is None}
        ds = {d: t for d, t in c["dimensions"].items() if denied(role, f"{name}.{d}") is None}
        if ms or ds:
            cubes[name] = {"measures": ms, "dimensions": ds, "joins": c["joins"], "description": c.get("description", ""), "docs": c.get("docs", {})}
    # a join to a cube the role cannot see is no use to it
    for c in cubes.values():
        c["joins"] = {j for j in (c["joins"] or ()) if j in cubes} if c["joins"] is not None else None
    return cat.Catalog(cubes)


def catalog_text(catalog: cat.Catalog) -> str:
    """The catalog as the model reads it: each cube with what it is, what it joins to, and every member with its type and meaning."""
    lines = []
    for name, c in sorted(catalog.cubes.items()):
        lines.append(f"cube {name}" + (f" (joins: {', '.join(sorted(c['joins']))})" if c["joins"] else "") + (f": {c['description']}" if c.get("description") else ""))
        for kind, label in (("measures", "measure"), ("dimensions", "dimension")):
            for m, t in sorted(c[kind].items()):
                doc = c.get("docs", {}).get(m, "")
                lines.append(f"  {label} {name}.{m} [{t}]" + (f": {doc}" if doc else ""))
    return "\n".join(lines)


def reference_text() -> str:
    """The spec reference generated from the schema (docs/dashboard-spec-reference.md): a weaker or cheaper model needs the exact fields, not only the cheat sheet."""
    if not SPEC_REFERENCE:
        return ""
    try:
        from dashspec.docs import generate
        text = generate().split("\n", 4)[-1].strip()
        # the role paragraph names members some roles cannot read; the model is only told about what this role can (see the catalog below)
        lines, out, skip = text.split("\n"), [], False
        for line in lines:
            if line.startswith("- **Roles:**"):
                skip = True
                continue
            if skip and (line.startswith("- ") or not line.strip()):
                skip = False
            if not skip:
                out.append(line)
        return "\n".join(out)
    except Exception:  # noqa: BLE001 (a missing schema file must not stop a build)
        return ""


def example_spec(catalog: cat.Catalog, role: str) -> str:
    """Complete specs that are valid for this role, composed from the catalog it may read (so they never name a member the role cannot see)."""
    from builder import composer
    out = []
    for title, ask in (("a dashboard with KPIs, a time chart, breakdowns, a table and a treemap", "revenue and orders by month, by region and top products, a table of latest orders and a treemap"),
                       ("a drill-down line chart and a pie with click-to-filter, in Turkish, with labels in Turkish", "Türkçe: yıl ay gün drill çizgi grafik ve alt kategoriye göre pasta grafiği"),
                       ("an inventory dashboard", "stock status and an excess stock table")):
        comp = composer.compose(ask, catalog, role)
        if comp.spec:
            out.append(f"# {title}\n" + yaml.safe_dump(comp.spec, sort_keys=False, allow_unicode=True, width=140))
    return "\n---\n".join(out[:2])


def system_blocks(catalog: cat.Catalog, role: str) -> list[dict]:
    visible = visible_catalog(catalog, role)
    text = SYSTEM.format(guide=SPEC_GUIDE, reference=reference_text(), example=example_spec(visible, role), catalog=catalog_text(visible))
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


# ------------------------------------------------------------------------------------------------------------------ checking a submission
def check_submission(text: str, catalog: cat.Catalog, role: str) -> tuple[dict | None, list[str]]:
    """-> ({ yaml, spec, notes }, []) for a spec this role can render, or (None, problems) to give back to the model."""
    if len(text) > MAX_YAML:
        return None, [f"the file is too long ({len(text)} characters, at most {MAX_YAML})"]
    text = re.sub(r"^\s*```(?:ya?ml)?[ \t]*\n|\n[ \t]*```\s*$", "", text)             # a model sometimes wraps the file in a code fence
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, [f"not valid YAML: {str(e)[:200]}"]
    if not isinstance(spec, dict):
        return None, ["the file must be a YAML mapping"]
    notes = []
    spec["id"] = "draft"
    spec["roles"] = [role]                         # the role rules are checked for the user who asked, whatever the model wrote
    if isinstance(spec.get("theme"), dict) and spec["theme"].pop("logo", None):
        notes.append("A logo was removed: builder drafts cannot load images.")
    stripped = False
    for p in spec.get("panels", []) if isinstance(spec.get("panels"), list) else []:
        if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("markdown"), str):
            clean = LINK.sub(r"\1", p["markdown"])
            stripped, p["markdown"] = stripped or clean != p["markdown"], clean
    if stripped:
        notes.append("Links in text panels were removed: a draft cannot point readers at other sites.")
    errors, used = validate(spec, catalog)
    if errors:
        return None, errors[:12]
    return {"yaml": yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=140), "spec": compile_spec(spec, used, catalog), "notes": notes}, []


# ------------------------------------------------------------------------------------------------------------------ the loop
def _dict(block) -> dict:
    return block.model_dump() if hasattr(block, "model_dump") else dict(vars(block))


def run_build(client, catalog: cat.Catalog, role: str, prompt: str, current_yaml: str | None = None,
              log: Callable[[str, dict], None] = lambda kind, data: None, mode: str = "llm") -> dict:
    """Run the tool-use loop. `client` is an anthropic.Anthropic or the stand-in. -> { status: ok | cannot | failed, ... }."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    system = system_blocks(catalog, role)
    user = prompt.strip()
    if current_yaml:
        user += f"\n\nThe current dashboard (change it as asked and submit the complete file):\n```yaml\n{current_yaml}\n```"
    messages = [{"role": "user", "content": user}]
    log("request", {"model": provider.model(), "mode": mode, "role": role, "prompt": prompt, "refine": bool(current_yaml)})
    usage = {"input_tokens": 0, "output_tokens": 0, "turns": 0}
    failures, last_errors, summary = 0, [], ""
    out = {"status": "failed", "message": "", "yaml": None, "spec": None, "notes": [], "attempts": 0}
    for turn in range(MAX_TURNS):
        response = client.messages.create(max_tokens=MAX_TOKENS, tools=TOOLS, messages=messages, **provider.request_kwargs(system, EFFORT))
        usage["turns"] += 1
        usage["input_tokens"] += getattr(response.usage, "input_tokens", 0) or 0
        usage["output_tokens"] += getattr(response.usage, "output_tokens", 0) or 0
        log("assistant", {"turn": turn, "stop_reason": response.stop_reason, "content": [_dict(b) for b in response.content]})
        if response.stop_reason in ("refusal", "max_tokens"):
            out["message"] = "The model refused the request." if response.stop_reason == "refusal" else "The answer was cut off; try a shorter request."
            break
        text = " ".join(b.text for b in response.content if b.type == "text").strip()
        calls = [b for b in response.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": response.content})
        if not calls:
            messages.append({"role": "user", "content": "Call submit_dashboard with the YAML, or cannot_build with the reason."})
            summary = text or summary
            continue
        results, done = [], False
        for call in calls:
            args = dict(call.input)
            if call.name == "cannot_build":
                out.update(status="cannot", message=str(args.get("reason", "")).strip()[:600])
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": "ok"})
                done = True
            elif call.name == "submit_dashboard":
                failures_before = failures
                built, problems = check_submission(str(args.get("yaml", "")), catalog, role)
                out["attempts"] += 1
                log("submission", {"attempt": out["attempts"], "problems": problems})
                if built:
                    out.update(status="ok", yaml=built["yaml"], spec=built["spec"], notes=built["notes"], message=str(args.get("summary") or text or summary).strip()[:600])
                    results.append({"type": "tool_result", "tool_use_id": call.id, "content": "accepted"})
                    done = True
                else:
                    failures, last_errors = failures_before + 1, problems
                    results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                                    "content": "The checker found problems. Fix all of them and submit the complete file again:\n- " + "\n- ".join(problems)})
            else:
                results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": True, "content": f"unknown tool {call.name}"})
        messages.append({"role": "user", "content": results})
        if done:
            break
        if failures >= MAX_ATTEMPTS:
            out["message"] = "The dashboard could not be made valid after %d tries." % failures
            break
    else:
        out["message"] = out["message"] or "The model did not finish."
    if out["status"] == "failed":
        out["problems"] = last_errors
    out["usage"], out["mode"], out["model"] = usage, mode, provider.model() if mode == "llm" else "rule-based stand-in"
    log("result", {k: v for k, v in out.items() if k not in ("spec",)})
    return out


EXAMPLES = {
    "sales": ["Monthly revenue by channel and the top 5 products, with a table of the latest orders",
              "Revenue and orders by region and country; click a bar to filter the rest",
              "Revenue by category as a treemap, and the product mix by month",
              "Türkçe satış panosu: aylık gelir, bölgeye göre gelir ve son siparişler"],
    "inventory": ["Stock status and the reorder list", "Overstock and excess stock, top 10", "Envanter durumu ve yeniden sipariş listesi, Türkçe"],
}


def examples_for(role: str) -> list[str]:
    """Requests that work for this role (the stand-in understands them; they are also good starting points for the model)."""
    return EXAMPLES["inventory"] if role in ("purchasing", "marketing") else EXAMPLES["sales"]


def check_catalog(model_dir: str) -> cat.Catalog:
    return cat.from_model(model_dir)


__all__ = ["run_build", "check_submission", "visible_catalog", "catalog_text", "system_blocks", "ROLES", "ROLE_CUBES", "json"]
