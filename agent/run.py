"""Draft this week's inventory proposals.

  python -m agent.run [--mode auto|rules|llm] [--dry-run] [--max-proposals 12]

`rules` drafts from the mart's own suggestions (no model, no key). `llm` has Claude do it through read-only tools
and needs ANTHROPIC_API_KEY (AGENT_MODEL, AGENT_EFFORT optional). `auto` (default) picks llm when a key is set.
Either way the batch goes to the actions service, which validates every proposal again and stores the valid ones
for a person to approve; the agent itself can approve nothing. Each run writes a JSONL log (every request, tool
call and result in llm mode) and prints an evaluation against the mart's suggested quantities.

Env: AGENT_CLIENT_SECRET, KEYCLOAK_TOKEN_URL, AUTH_URL, CUBE_URL, ACTIONS_URL (defaults suit the compose network),
AGENT_LOG_DIR (default ./agent-logs).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

from agent import drafting, llm
from agent.evaluate import evaluate
from agent.inventory_api import InventoryApi


def make_log(path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8")

    def log(event: str, payload: dict) -> None:
        handle.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "event": event, **payload}, default=str) + "\n")
        handle.flush()

    return log, handle


def products_of(p: dict) -> tuple:
    payload = p["payload"]
    ids = payload.get("product_ids") or [line["product_id"] for line in payload.get("lines", [])]
    return p["kind"], tuple(sorted(int(i) for i in ids))


def drop_duplicates(proposals: list[dict], open_proposals: list[dict]) -> tuple[list[dict], list[dict]]:
    """Proposals that repeat one still waiting for a decision (same kind, same products) are not drafted again."""
    waiting = {products_of(p) for p in open_proposals}
    keep = [p for p in proposals if products_of(p) not in waiting]
    return keep, [p for p in proposals if products_of(p) in waiting]


def build(api, mode: str, log, max_proposals: int, client_factory=None):
    """Returns (proposals, info, at_risk, excess) for the chosen mode."""
    if mode == "llm":
        client = client_factory() if client_factory else __import__("anthropic").Anthropic()
        proposals, info, session = llm.run_llm(client, api, log, max_proposals)
        at_risk = session.read_at_risk or api.at_risk(100)
        excess = session.read_excess or api.excess(100)
        return proposals, info, at_risk, excess
    at_risk, excess, evidence = api.at_risk(100), api.excess(100), api.offer_evidence()
    log("data", {"at_risk": len(at_risk), "excess": len(excess), "evidence": evidence})
    proposals = drafting.strip_private(drafting.draft(at_risk, excess, evidence, max_proposals))
    return proposals, {"stop": "rules", "summary": "", "usage": {}, "model": None}, at_risk, excess


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("auto", "rules", "llm"), default="auto")
    ap.add_argument("--dry-run", action="store_true", help="draft and evaluate, but submit nothing")
    ap.add_argument("--max-proposals", type=int, default=12)
    args = ap.parse_args(argv)
    mode = args.mode
    if mode == "auto":
        mode = "llm" if os.environ.get("ANTHROPIC_API_KEY") else "rules"
    if mode == "llm" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("llm mode needs ANTHROPIC_API_KEY", file=sys.stderr)
        return 2
    run_id = f"agent-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{mode}"
    log_path = pathlib.Path(os.environ.get("AGENT_LOG_DIR", "agent-logs")) / f"{run_id}.jsonl"
    log, handle = make_log(log_path)
    try:
        api = InventoryApi()
        log("start", {"run_id": run_id, "mode": mode, "dry_run": args.dry_run})
        proposals, info, at_risk, excess = build(api, mode, log, args.max_proposals)
        proposals, repeated = drop_duplicates(proposals, api.open_proposals())
        if repeated:
            log("skipped_duplicates", {"titles": [p["title"] for p in repeated]})
            print(f"skipped {len(repeated)} proposal(s) already waiting for a decision")
        results = None
        if proposals and not args.dry_run:
            results = api.submit(run_id, proposals)["results"]
            log("submitted", {"results": results})
        report = evaluate(proposals, at_risk, excess, results)
        log("evaluation", report)
    finally:
        handle.close()
    print(f"run {run_id} ({mode}{', dry run' if args.dry_run else ''}): {len(proposals)} proposals drafted")
    for i, p in enumerate(proposals):
        flag = ""
        if results is not None:
            r = next((x for x in results if x["seq"] == i), None)
            flag = "  [stored]" if r and r["ok"] else f"  [REFUSED: {r['reason'] if r else '?'}]"
        print(f"  {i + 1}. {p['kind']:<15} {p['title']}{flag}\n     {p['rationale']}")
    print("evaluation:", json.dumps({k: v for k, v in report.items() if k != "deviations"}))
    for d in report["deviations"]:
        print("  deviation:", d)
    if info.get("summary"):
        print("model summary:", info["summary"])
    if info.get("usage"):
        print("usage:", info["usage"])
    print("log:", log_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
