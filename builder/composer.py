"""What every composer shares: reading words (Turkish accents folded), the composition result and the page layout; and the dispatcher that picks the composer for a model.

A model that ships a rule-based recipe (`builder: { recipe: <name> }` in its model.config.yml, a module in builder/recipes/: a model add-on, like agent/ and actions/) is
composed by it; every other model by generic.py, which reads only the catalog (and the model's `vocabulary`). See PLAN-decouple.md phase 4.
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field

TR_MAP = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iissgguuoocc")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower().translate(TR_MAP)).strip()


def has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}", text) for w in words)


def word(text: str, *words: str) -> bool:
    """Whole words only: "ay" (month) must not match "ayrica" (also)."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


@dataclass
class Composition:
    spec: dict | None = None
    reason: str = ""
    notes: list[str] = field(default_factory=list)


FLEXIBLE = {"timeseries": (8, 4), "treemap": (7, 5), "bar": (6, 6), "pie": (5, 7)}


def layout(panels: list[dict]) -> list[list[dict]]:
    """Rows of 12 columns: kpis, tables and notes take a row; two charts share one (the first sets the split); slicers next to each other share one evenly (up to 4)."""
    rows, i = [], 0
    while i < len(panels):
        p = panels[i]
        nxt = panels[i + 1] if i + 1 < len(panels) else None
        if p["type"] == "slicer":
            run = [x["id"] for x in panels[i:i + 4]]
            run = run[:next((k for k, x in enumerate(panels[i:i + 4]) if x["type"] != "slicer"), len(run))]
            rows.append([{sid: 12 // len(run) + (12 % len(run) if k == 0 else 0)} for k, sid in enumerate(run)])
            i += len(run)
            continue
        if p["type"] in FLEXIBLE and nxt and nxt["type"] in FLEXIBLE:
            a, c = FLEXIBLE[p["type"]]
            if nxt["type"] == "pie" and p["type"] != "pie":
                a, c = 7, 5                                           # a pie needs room for its legend
            if p["type"] == nxt["type"] == "timeseries":
                a, c = 6, 6                                           # two time charts share a row evenly
            rows.append([{p["id"]: a}, {nxt["id"]: c}])
            i += 2
        else:
            rows.append([{p["id"]: 12}])
            i += 1
    return rows



RECIPES = {"adventureworks": "builder.recipes.adventureworks"}


def recipe_of(catalog):
    """The recipe module a model names in its config, else None."""
    name = ((catalog.config.get("builder") or {}).get("recipe"))
    return importlib.import_module(RECIPES[name]) if name in RECIPES else None


def compose(prompt: str, catalog, role: str, current_yaml: str | None = None, focus: str | None = None) -> Composition:
    """A dashboard (or an edit of one) for a request, from the catalog the role may read."""
    recipe = recipe_of(catalog)
    if recipe:
        return recipe.compose(prompt, catalog, role, current_yaml, focus)
    from builder import generic
    return generic.compose(prompt, catalog, role, current_yaml, focus)


def example_requests(catalog) -> list[tuple[str, str]]:
    """The requests whose compositions the model's prompt shows as examples: the recipe's, else made from the catalog."""
    recipe = recipe_of(catalog)
    if recipe:
        return list(recipe.EXAMPLE_REQUESTS)
    from builder import generic
    return generic.example_requests(catalog)


def suggestions(catalog, lang: str = "en") -> list[str]:
    """What the builder page offers to type: the model's `builder.examples` (a list per language), else its recipe's, else ones made from the catalog."""
    own = (catalog.config.get("builder") or {}).get("examples") if catalog is not None else None
    if own:
        return list(own.get(lang) or own.get("en") or [])
    recipe = recipe_of(catalog) if catalog is not None else importlib.import_module(RECIPES["adventureworks"])          # no catalog: the one recipe there is
    if recipe:
        return list(recipe.EXAMPLES["sales"].get(lang, recipe.EXAMPLES["sales"]["en"]))
    from builder import generic
    return generic.suggestions(catalog).get(lang) or generic.suggestions(catalog)["en"]
