import json

from agent import run
from agent.tests.conftest import FakeApi, row


def test_rules_mode_end_to_end_with_a_dry_run_and_a_submit(tmp_path, monkeypatch, capsys):
    api = FakeApi(at_risk=[row(1), row(2, category="Frames")], excess=[row(10, status="overstock", suggested_discount_pct=20.0, excess_value=2000.0)])
    monkeypatch.setattr(run, "InventoryApi", lambda: api)
    monkeypatch.setenv("AGENT_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run.main(["--dry-run"]) == 0
    assert api.submitted is None
    assert run.main([]) == 0
    run_id, proposals = api.submitted
    assert run_id.endswith("-rules") and len(proposals) == 3 and all("_value" not in p for p in proposals)
    out = capsys.readouterr().out
    assert "[stored]" in out and "quantity_matches_suggestion" in out
    log = [json.loads(line) for f in tmp_path.glob("*.jsonl") for line in f.read_text().splitlines()]
    assert {e["event"] for e in log} >= {"start", "data", "submitted", "evaluation"}


def test_llm_mode_without_a_key_refuses_to_start(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run.main(["--mode", "llm"]) == 2


def test_proposals_already_waiting_are_not_drafted_again():
    a = {"kind": "work_order", "title": "a", "rationale": "r", "payload": {"lines": [{"product_id": 2, "qty": 1}, {"product_id": 1, "qty": 3}]}}
    b = {"kind": "campaign", "title": "b", "rationale": "r", "payload": {"product_ids": [10], "discount_pct": 10, "days": 30}}
    waiting = [{"kind": "work_order", "payload": {"lines": [{"product_id": 1, "qty": 9}, {"product_id": 2, "qty": 9}]}}]
    keep, repeated = run.drop_duplicates([a, b], waiting)
    assert keep == [b] and repeated == [a]
