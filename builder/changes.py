"""What changed between two versions of a saved dashboard, in a form the page can word in either language.

`describe(old_yaml, new_yaml)` returns a short list of changes, each a dict with a `kind` and the facts that kind needs:
created | title {from, to} | page {fields} | panel_added {id, title, type} | panel_removed {id, title, type} | panel_changed {id, title, fields} |
layout | filter_added {id, label} | filter_removed {id, label} | filter_changed {id, label, fields} | unknown.
The page words them (see `versionChanges` in dashboard/static/render/strings.js); nothing here is text for a reader. Dicts are compared as they were saved, so a re-ordered
key is not a change and a changed value is.
"""
from __future__ import annotations

import yaml

MAX_CHANGES = 20
PAGE_KEYS = ("description", "locale", "currency", "time", "tags", "theme")      # the dashboard's own fields; title has its own kind, the rest are not a person's to change
LAYOUT_KEYS = ("layout", "tabs")


def _load(text: str) -> dict | None:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _by_id(items) -> dict:
    return {x["id"]: x for x in items or [] if isinstance(x, dict) and "id" in x}


def _changed_keys(a: dict, b: dict) -> list[str]:
    return sorted(k for k in {*a, *b} if a.get(k) != b.get(k))


def describe(old_text: str | None, new_text: str) -> list[dict]:
    """The changes from `old_text` to `new_text`; the first version (old_text None) is `created`."""
    if old_text is None:
        return [{"kind": "created"}]
    old, new = _load(old_text), _load(new_text)
    if old is None or new is None:
        return [{"kind": "unknown"}]
    out: list[dict] = []
    if old.get("title") != new.get("title"):
        out.append({"kind": "title", "from": old.get("title"), "to": new.get("title")})
    page = [k for k in PAGE_KEYS if old.get(k) != new.get(k)]
    if page:
        out.append({"kind": "page", "fields": page})
    old_panels, new_panels = _by_id(old.get("panels")), _by_id(new.get("panels"))
    for pid, p in new_panels.items():
        if pid not in old_panels:
            out.append({"kind": "panel_added", "id": pid, "title": p.get("title") or pid, "type": p.get("type")})
    for pid, p in old_panels.items():
        if pid not in new_panels:
            out.append({"kind": "panel_removed", "id": pid, "title": p.get("title") or pid, "type": p.get("type")})
    for pid, p in new_panels.items():
        if pid in old_panels and old_panels[pid] != p:
            out.append({"kind": "panel_changed", "id": pid, "title": p.get("title") or pid, "fields": _changed_keys(old_panels[pid], p)})
    if any(old.get(k) != new.get(k) for k in LAYOUT_KEYS):
        out.append({"kind": "layout"})
    old_filters, new_filters = _by_id(old.get("filters")), _by_id(new.get("filters"))
    for fid, f in new_filters.items():
        if fid not in old_filters:
            out.append({"kind": "filter_added", "id": fid, "label": f.get("label") or fid})
        elif old_filters[fid] != f:
            out.append({"kind": "filter_changed", "id": fid, "label": f.get("label") or fid, "fields": _changed_keys(old_filters[fid], f)})
    for fid, f in old_filters.items():
        if fid not in new_filters:
            out.append({"kind": "filter_removed", "id": fid, "label": f.get("label") or fid})
    return out[:MAX_CHANGES] or [{"kind": "unknown"}]
