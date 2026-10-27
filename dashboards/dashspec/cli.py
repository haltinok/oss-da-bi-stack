import argparse
import json
import os
import pathlib
import sys

import yaml

from . import catalog as cat
from .compile import compile_spec
from .lint import cube_planner, lint
from .validate import validate

REPO = pathlib.Path(__file__).resolve().parents[2]


def _catalog(args):
    if args.cube_url:
        token = os.environ.get("CUBE_TOKEN")
        if not token:
            sys.exit("--cube-url needs a Cube JWT in the CUBE_TOKEN environment variable")
        return cat.from_cube(args.cube_url, token)
    return cat.from_model(args.model)


def _load(path):
    try:
        spec = yaml.safe_load(pathlib.Path(path).read_text())
    except yaml.YAMLError as e:
        return None, [f"not valid YAML: {e}"]
    if not isinstance(spec, dict):
        return None, ["the file must be a YAML mapping"]
    return spec, []


def _check(path, catalog):
    spec, errs = _load(path)
    used = {}
    if spec is not None:
        errs, used = validate(spec, catalog)
    return spec, used, errs


def cmd_validate(args):
    catalog, bad = _catalog(args), 0
    for path in args.files:
        _, _, errs = _check(path, catalog)
        if errs:
            bad += 1
            print(f"{path}: {len(errs)} problem(s)")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"{path}: ok")
    return 1 if bad else 0


def cmd_compile(args):
    spec, used, errs = _check(args.file, _catalog(args))
    if errs:
        for e in errs:
            print(f"{args.file}: {e}", file=sys.stderr)
        return 1
    text = json.dumps(compile_spec(spec, used, _catalog(args)), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        out = pathlib.Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_build(args):
    """Compile every dashboards/*.yml into <out>/<id>.json and write <out>/index.json (the list the renderer shows)."""
    catalog = _catalog(args)
    src, out = pathlib.Path(args.dir), pathlib.Path(args.out)
    index, bad = [], 0
    for path in sorted(src.glob("*.yml")):
        spec, used, errs = _check(path, catalog)
        if errs:
            bad += 1
            print(f"{path}: {len(errs)} problem(s)", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            continue
        if path.stem != spec["id"]:
            bad += 1
            print(f"{path}: the file name must be the dashboard id ('{spec['id']}.yml')", file=sys.stderr)
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{spec['id']}.json").write_text(json.dumps(compile_spec(spec, used, catalog), indent=2, ensure_ascii=False) + "\n")
        index.append({"id": spec["id"], "title": spec["title"], "description": spec.get("description", ""), "roles": spec.get("roles", []), **({"tags": spec["tags"]} if spec.get("tags") else {})})
    if bad:
        return 1
    stale = {p.name for p in out.glob("*.json")} - {f"{i['id']}.json" for i in index} - {"index.json"} if out.is_dir() else set()
    for name in sorted(stale):      # a dashboard that was deleted must not stay served
        (out / name).unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    print(f"built {len(index)} dashboard(s) into {out}")
    return 0


def cmd_lint(args):
    """Validate, then ask Cube whether a pre-aggregation serves each query of each dashboard. Warnings do not fail the run unless --strict."""
    token = os.environ.get("CUBE_TOKEN")
    if not token or not args.cube_url:
        sys.exit("lint asks a running Cube: pass --cube-url and set CUBE_TOKEN to a Cube JWT (role admin)")
    plan = cube_planner(args.cube_url, token)
    catalog, status = cat.from_model(args.model), 0        # the members and joins come from the model files; Cube only plans queries
    for path in args.files:
        spec, used, errs = _check(path, catalog)
        if errs:
            print(f"{path}: {len(errs)} problem(s) (run validate)")
            status = 1
            continue
        found = lint(compile_spec(spec, used, catalog), plan)
        print(f"{path}: " + ("every query is served by a pre-aggregation" if not found else f"{len(found)} warning(s)"))
        for severity, message in found:
            print(f"  - {severity}: {message}")
        if found and args.strict:
            status = 1
    return status


def cmd_docs(args):
    """Write the spec reference generated from the schema (docs/dashboard-spec-reference.md)."""
    from .docs import generate
    out = pathlib.Path(args.output)
    out.write_text(generate())
    print(f"wrote {out}")
    return 0


def cmd_semantic(args):
    """Write the semantic-layer page generated from the Cube model (docs/semantic-layer.md)."""
    from .semantic import generate
    out = pathlib.Path(args.output)
    out.write_text(generate(cat.from_model(args.model)))
    print(f"wrote {out}")
    return 0


def cmd_meta(args):
    catalog = _catalog(args)
    if args.json:
        json.dump({c: {**v, "joins": sorted(v["joins"]) if v["joins"] is not None else None} for c, v in sorted(catalog.cubes.items())},
                  sys.stdout, indent=2)
        print()
        return 0
    for name, c in sorted(catalog.cubes.items()):
        print(f"cube {name}" + (f"  (joins: {', '.join(sorted(c['joins']))})" if c["joins"] else ""))
        if c.get("description"):
            print(f"  {c['description']}")
        print("  measures:   " + ", ".join(f"{m} [{t}]" for m, t in sorted(c["measures"].items())))
        print("  dimensions: " + ", ".join(f"{d} [{t}]" for d, t in sorted(c["dimensions"].items())))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dashspec", description="Validate and compile dashboard specs (YAML) against the Cube model.")
    src = argparse.ArgumentParser(add_help=False)
    src.add_argument("--model", default=str(REPO / "cube" / "model"), help="Cube model directory (default: cube/model)")
    src.add_argument("--cube-url", help="read the members from a running Cube instead (a Cube JWT in $CUBE_TOKEN; no join check)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", parents=[src], help="schema and member checks; exit 1 on any problem")
    v.add_argument("files", nargs="+")
    v.set_defaults(fn=cmd_validate)
    c = sub.add_parser("compile", parents=[src], help="validate, then write the JSON the renderer loads")
    c.add_argument("file")
    c.add_argument("-o", "--output")
    c.set_defaults(fn=cmd_compile)
    b = sub.add_parser("build", parents=[src], help="compile every dashboard in a directory (default dashboards/) into dashboards/build")
    b.add_argument("--dir", default=str(REPO / "dashboards"))
    b.add_argument("--out", default=str(REPO / "dashboards" / "build"))
    b.set_defaults(fn=cmd_build)
    li = sub.add_parser("lint", parents=[src], help="does a Cube pre-aggregation serve every query? (needs --cube-url and $CUBE_TOKEN)")
    li.add_argument("files", nargs="+")
    li.add_argument("--strict", action="store_true", help="exit 1 on any warning (use it for a dashboard on the 250M dataset)")
    li.set_defaults(fn=cmd_lint)
    dd = sub.add_parser("docs", help="write the spec reference, generated from the schema")
    dd.add_argument("-o", "--output", default=str(REPO / "docs" / "dashboard-spec-reference.md"))
    dd.set_defaults(fn=cmd_docs)
    se = sub.add_parser("semantic", parents=[src], help="write the semantic-layer page (what the model offers, who may read what)")
    se.add_argument("-o", "--output", default=str(REPO / "docs" / "semantic-layer.md"))
    se.set_defaults(fn=cmd_semantic)
    m = sub.add_parser("meta", parents=[src], help="the catalog of cubes, measures and dimensions (for the authoring agent)")
    m.add_argument("--json", action="store_true")
    m.set_defaults(fn=cmd_meta)
    args = ap.parse_args(argv)
    return args.fn(args)
