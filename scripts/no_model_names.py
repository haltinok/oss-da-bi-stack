#!/usr/bin/env python3
"""The guard of PLAN-decouple.md: the app knows no model.

Lists every place under the app folders that names a cube or a member of a model the repo ships (cube/model, models/<name>/cube): a qualified member
(`internet_sales.revenue`, only a member that really exists, so `dates.length` is not a hit) or a quoted cube name with an underscore (`"internet_sales"`; a plain word such as "calendar" or "items" is also a cube name of some model and says nothing).
Model add-ons (agent/, actions/, builder/recipes/), tests, example dashboards, the Cube model, dbt and Airflow may name members and are not scanned.

  python scripts/no_model_names.py            # warning mode (phases 0-4): prints the hits as GitHub annotations, exits 0
  python scripts/no_model_names.py --strict   # phase 5: exits 1 on any hit that scripts/no-model-names.allow does not list
  python scripts/no_model_names.py --count    # one line: the number of hits

The allow-list has one `path  # reason` per line: every hit in that file is justified.
"""
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
SCAN = ["dashboard", "builder", "dashboards/dashspec", "lab", "admin", "auth", "cube/cube.js"]
SKIP_DIRS = {"tests", "node_modules", "__pycache__", "screenshots", ".venv"}
ADD_ONS = ("builder/recipes/",)          # a model's hand-made rule-based recipe lives beside the app, named in the model's model.config.yml
SUFFIXES = {".py", ".js", ".mjs", ".html", ".json", ".css", ".yml", ".yaml", ".md", ".template"}


def model_dirs():
    return [REPO / "cube" / "model", *sorted((REPO / "models").glob("*/cube"))]


def names():
    """-> (cubes, members) over every model: {'dates', ...}, {'dates.full_date', ...}"""
    cubes, members = set(), set()
    for d in model_dirs():
        for path in d.rglob("*.y*ml"):
            for cube in (yaml.safe_load(path.read_text()) or {}).get("cubes", []):
                cubes.add(cube["name"])
                members.update(f"{cube['name']}.{m['name']}" for m in [*cube.get("measures", []), *cube.get("dimensions", [])])
    return cubes, members


def files():
    for entry in SCAN:
        root = REPO / entry
        for path in ([root] if root.is_file() else sorted(root.rglob("*"))):
            if path.is_file() and path.suffix in SUFFIXES and not SKIP_DIRS & set(path.relative_to(REPO).parts) and not path.relative_to(REPO).as_posix().startswith(ADD_ONS):
                yield path


def allowed():
    out = set()
    list_file = REPO / "scripts" / "no-model-names.allow"
    if list_file.exists():
        for line in list_file.read_text().splitlines():
            line = line.split("#")[0].strip()
            if line:
                out.add(line)
    return out


def hits():
    cubes, members = names()
    quoted = re.compile(r"""["'](%s)["']""" % "|".join(sorted((c for c in cubes if "_" in c), key=len, reverse=True)))
    qualified = re.compile(r"\b([a-z][a-z_]*)\.([a-z][a-z_]*)\b")
    for path in files():
        for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            found = {f"{a}.{b}" for a, b in qualified.findall(line) if f"{a}.{b}" in members}
            found |= {m.group(1) for m in quoted.finditer(line)}
            for name in sorted(found):
                yield path.relative_to(REPO).as_posix(), n, name


def main():
    allow, found = allowed(), list(hits())
    bad = [h for h in found if h[0] not in allow]
    if "--count" in sys.argv:
        print(len(bad))
        return 0
    for path, n, name in bad:
        print(f"::warning file={path},line={n}::the app names the model: {name} (it comes from /v1/meta, meta: or model.config.yml)")
    by_file = {}
    for path, _, _ in bad:
        by_file[path] = by_file.get(path, 0) + 1
    print(f"\nno-model-names: {len(bad)} hit(s) in {len(by_file)} file(s)" + (f" ({len(found) - len(bad)} more allowed)" if len(found) != len(bad) else ""))
    for path, count in sorted(by_file.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4}  {path}")
    return 1 if bad and "--strict" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())
