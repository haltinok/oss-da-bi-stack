"""Try the builder from the command line (no service, no sign-in).

  PYTHONPATH=dashboards:. uv run --with pyyaml --with 'jsonschema>=4.18' python -m builder.cli "monthly revenue by channel, top 5 products" --role rep
  ... --current dashboards/regional-sales.yml "make the chart a line"     # change an existing file
  ... --mode llm                                                          # Claude (needs ANTHROPIC_API_KEY); the default uses it when the key is set
"""
import argparse
import os
import pathlib
import sys

from dashspec import catalog as cat

from builder import core, provider
from builder.standin import StandInClient

REPO = pathlib.Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt")
    ap.add_argument("--role", default="admin", choices=core.ROLES)
    ap.add_argument("--model-dir", default=str(REPO / "cube" / "model"))
    ap.add_argument("--current", help="a dashboard YAML to change")
    ap.add_argument("--mode", choices=("auto", "llm", "standin"), default="auto")
    ap.add_argument("-o", "--output", help="write the YAML here")
    args = ap.parse_args(argv)
    mode = args.mode if args.mode != "auto" else ("llm" if provider.has_key() else "standin")
    catalog = cat.from_model(args.model_dir)
    if mode == "llm":
        client = provider.make_client(120)
    else:
        client = StandInClient(catalog, args.role)
    current = pathlib.Path(args.current).read_text() if args.current else None
    result = core.run_build(client, catalog, args.role, args.prompt, current, mode=mode, log=lambda kind, data: print(f"[{kind}] {data}", file=sys.stderr) if os.environ.get("BUILDER_DEBUG") else None)
    print(f"# {result['status']} ({result['mode']}, {result['attempts']} submission(s)): {result['message']}", file=sys.stderr)
    for n in result["notes"]:
        print(f"# note: {n}", file=sys.stderr)
    for p in result.get("problems", []):
        print(f"# problem: {p}", file=sys.stderr)
    if result["yaml"]:
        if args.output:
            pathlib.Path(args.output).write_text(result["yaml"])
        else:
            print(result["yaml"])
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
