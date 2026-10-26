"""The HTTP service: who may call it, what each role sees, the rate limit, the modes, and a build end to end (no Keycloak, no model API)."""
import json
import os
import pathlib
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

REPO = pathlib.Path(__file__).resolve().parents[2]
os.environ.update(KEYCLOAK_ISSUER="http://kc/realms/spike", KEYCLOAK_JWKS_URL="http://kc/certs", BUILDER_MODEL_DIR=str(REPO / "cube" / "model"))
os.environ.pop("ANTHROPIC_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from builder import main  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
main.jwks.get_signing_key_from_jwt = lambda raw: SimpleNamespace(key=KEY.public_key())
client = TestClient(main.app)


def token(role="manager", user="alice", azp="dashboard", issuer="http://kc/realms/spike", exp=3600):
    claims = {"iss": issuer, "azp": azp, "preferred_username": user, "exp": int(time.time()) + exp, "realm_access": {"roles": [role] if role else []}}
    return {"Authorization": "Bearer " + jwt.encode(claims, KEY, algorithm="RS256")}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    main._recent.clear()
    monkeypatch.setattr(main, "MODE", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_healthz_needs_no_token():
    assert client.get("/healthz").json() == {"ok": True}


@pytest.mark.parametrize("headers,status", [
    ({}, 401), ({"Authorization": "Bearer nonsense"}, 401), (token(azp="other-client"), 401), (token(issuer="http://evil/realms/x"), 401),
    (token(exp=-10), 401), (token(role=None), 403), (token(role="agent"), 403),
])
def test_only_signed_in_dashboard_users_with_a_role_may_call(headers, status):
    assert client.get("/info", headers=headers).status_code == status


def test_info_says_which_mode_answers():
    info = client.get("/info", headers=token("rep", "ralf")).json()
    assert info["mode"] == "standin" and info["role"] == "rep" and info["user"] == "ralf" and "rule-based" in info["model"] and "fixed set of phrases" in info["note"]


def test_catalog_is_what_the_role_may_read():
    rep = {c["cube"]: c for c in client.get("/catalog", headers=token("rep")).json()}
    assert "inventory_health" not in rep and "gross_profit" not in {m["name"] for m in rep["internet_sales"]["measures"]}
    assert rep["internet_sales"]["measures"][0]["description"] and rep["internet_sales"]["joins"] == ["dates", "products", "territories"]
    assert {c["cube"] for c in client.get("/catalog", headers=token("purchasing")).json()} == {"inventory_health", "products"}
    assert "customers" in {c["cube"] for c in client.get("/catalog", headers=token("admin")).json()}


def test_build_end_to_end_with_the_stand_in():
    r = client.post("/build", headers=token("manager"), json={"prompt": "monthly revenue by channel and top 5 products"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and body["mode"] == "standin" and body["spec"]["id"] == "draft" and "id: draft" in body["yaml"]
    again = client.post("/build", headers=token("manager"), json={"prompt": "make it a line chart", "current_yaml": body["yaml"]}).json()
    assert again["status"] == "ok" and next(p for p in again["spec"]["panels"] if p["type"] == "timeseries")["style"] == "line"


def test_a_role_that_cannot_have_it_is_told_so_not_given_it():
    body = client.post("/build", headers=token("rep"), json={"prompt": "profit by region"}).json()
    assert body["status"] == "cannot" and "hidden from reps" in body["message"] and body["spec"] is None


def test_the_prompt_is_checked():
    h = token()
    assert client.post("/build", headers=h, json={"prompt": "x"}).status_code == 422
    assert client.post("/build", headers=h, json={"prompt": "y" * 2001}).status_code == 422
    assert client.post("/build", headers=h, json={"prompt": "revenue", "current_yaml": "z" * 30_001}).status_code == 422
    assert client.post("/build", headers=h, json={}).status_code == 422


def test_each_user_has_a_rate_limit(monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT", 2)
    for _ in range(2):
        assert client.post("/build", headers=token(user="busy"), json={"prompt": "revenue by month"}).status_code == 200
    limited = client.post("/build", headers=token(user="busy"), json={"prompt": "revenue by month"})
    assert limited.status_code == 429 and "2 dashboards an hour" in limited.json()["detail"]
    assert client.post("/build", headers=token(user="other"), json={"prompt": "revenue by month"}).status_code == 200


def test_llm_mode_needs_a_key_and_auto_follows_it(monkeypatch):
    monkeypatch.setattr(main, "MODE", "llm")
    r = client.post("/build", headers=token(), json={"prompt": "revenue by month"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    monkeypatch.setattr(main, "MODE", "auto")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    info = client.get("/info", headers=token()).json()
    assert info["mode"] == "llm" and info["model"] == main.core.MODEL and "language model" in info["note"]


def test_llm_mode_runs_the_same_loop_with_the_anthropic_client(monkeypatch):
    """With a key the service builds an Anthropic client; here a scripted one stands in, to show the loop, checks and result shape are shared."""
    from builder.tests.test_core import GOOD, Script, submit
    script = Script([submit(GOOD)])
    monkeypatch.setattr(main, "make_client", lambda m, role: script)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    body = client.post("/build", headers=token("manager"), json={"prompt": "regional sales"}).json()
    assert body["status"] == "ok" and body["mode"] == "llm" and body["model"] == main.core.MODEL and body["usage"]["input_tokens"] == 100
    assert script.calls[0]["system"][0]["cache_control"] and "cannot_build" in script.calls[0]["system"][0]["text"] and script.calls[0]["tools"][0]["name"] == "submit_dashboard"


def test_validate_checks_a_hand_edited_file_for_the_callers_role():
    good = client.post("/build", headers=token("manager"), json={"prompt": "revenue by month"}).json()["yaml"]
    ok = client.post("/validate", headers=token("manager"), json={"yaml": good}).json()
    assert ok["ok"] and ok["spec"]["id"] == "draft" and ok["problems"] == []
    broken = client.post("/validate", headers=token("manager"), json={"yaml": good.replace("internet_sales.revenue", "internet_sales.nope", 1)}).json()
    assert not broken["ok"] and broken["spec"] is None and any("internet_sales.nope" in p for p in broken["problems"])
    as_rep = client.post("/validate", headers=token("rep"), json={"yaml": good.replace("internet_sales.revenue", "internet_sales.gross_profit")}).json()
    assert not as_rep["ok"] and any("role 'rep' cannot read" in p for p in as_rep["problems"])
    assert client.post("/validate", json={"yaml": good}).status_code == 401
    assert client.post("/validate", headers=token("manager"), json={"yaml": ""}).status_code == 422


def test_info_offers_examples_that_fit_the_role():
    assert any("revenue" in e.lower() for e in client.get("/info", headers=token("manager")).json()["examples"])
    assert all("stock" in e.lower() or "envanter" in e.lower() for e in client.get("/info", headers=token("purchasing")).json()["examples"])


def test_every_example_builds_for_its_role():
    for role in ("manager", "rep", "admin", "purchasing", "marketing"):
        for ex in client.get("/info", headers=token(role)).json()["examples"]:
            assert client.post("/build", headers=token(role, user=f"{role}-ex"), json={"prompt": ex}).json()["status"] == "ok", (role, ex)


# ---------------------------------------------------------------------------------------------------------------- limits, errors, audit
def llm(monkeypatch, *answers):
    from builder.tests.test_core import Script
    script = Script(*answers)
    monkeypatch.setattr(main, "make_client", lambda m, role: script)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    return script


def test_usage_and_builds_left_follow_the_users_builds():
    h = token(user="counter")
    assert client.get("/info", headers=h).json()["builds_left"] == main.RATE_LIMIT
    client.post("/build", headers=h, json={"prompt": "revenue by month"})
    use = client.get("/usage", headers=h).json()
    assert use["builds_last_hour"] == 1 and use["builds_per_hour"] == main.RATE_LIMIT and use["tokens_today"] == 0 and use["mode"] == "standin"
    assert client.get("/info", headers=h).json()["builds_left"] == main.RATE_LIMIT - 1
    assert client.get("/usage").status_code == 401


def test_a_daily_token_budget_stops_a_user_until_tomorrow(monkeypatch):
    from builder.tests.test_core import GOOD, submit
    llm(monkeypatch, [submit(GOOD)], [submit(GOOD)])
    monkeypatch.setattr(main, "DAILY_TOKENS", 200)
    h = token("manager", "spender")
    assert client.post("/build", headers=h, json={"prompt": "regional sales"}).status_code == 200          # 150 tokens
    assert client.get("/usage", headers=h).json()["tokens_today"] == 150
    assert client.post("/build", headers=h, json={"prompt": "regional sales again"}).status_code == 200       # 300 now, over budget
    blocked = client.post("/build", headers=h, json={"prompt": "and once more"})
    assert blocked.status_code == 429 and "budget" in blocked.json()["detail"] and "midnight UTC" in blocked.json()["detail"]
    assert client.get("/usage", headers=token("manager", "someone-else")).json()["tokens_today"] == 0, "the budget is per user"


def test_tokens_reset_on_a_new_day(monkeypatch):
    main._tokens["old"] = ("1999-01-01", 10**9)
    assert main._tokens_today(main.User(name="old", role="rep")) == 0


def test_at_most_a_few_builds_run_at_once_and_a_refused_one_costs_nothing(monkeypatch):
    import threading
    monkeypatch.setattr(main, "_slots", threading.BoundedSemaphore(1))
    assert main._slots.acquire(blocking=False)
    h = token(user="impatient")
    r = client.post("/build", headers=h, json={"prompt": "revenue by month"})
    assert r.status_code == 503 and "busy" in r.json()["detail"]
    assert client.get("/usage", headers=h).json()["builds_last_hour"] == 0
    main._slots.release()
    assert client.post("/build", headers=h, json={"prompt": "revenue by month"}).status_code == 200


@pytest.mark.parametrize("status,words", [(401, "key was rejected"), (403, "key was rejected"), (500, "not reachable"), (None, "not reachable")])
def test_a_model_failure_is_reported_plainly_and_leaks_nothing(monkeypatch, status, words):
    secret = "sk-ant-api03-SECRET-do-not-leak"

    class Boom:
        def __init__(self):
            self.messages = SimpleNamespace(create=self.create)

        def create(self, **kw):
            err = RuntimeError(f"request failed for key {secret}")
            err.status_code = status
            raise err
    monkeypatch.setattr(main, "make_client", lambda m, role: Boom())
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    r = client.post("/build", headers=token(user="unlucky"), json={"prompt": "revenue by month"})
    assert r.status_code == 502 and words in r.json()["detail"] and secret not in r.text


def test_a_timeout_says_so(monkeypatch):
    class APITimeoutError(Exception):
        pass

    class Slow:
        def __init__(self):
            self.messages = SimpleNamespace(create=self.create)

        def create(self, **kw):
            raise APITimeoutError("timed out")
    monkeypatch.setattr(main, "make_client", lambda m, role: Slow())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    r = client.post("/build", headers=token(user="waiting"), json={"prompt": "revenue by month"})
    assert r.status_code == 502 and "took too long" in r.json()["detail"]
    assert client.get("/usage", headers=token(user="waiting")).json()["builds_last_hour"] == 1       # the attempt happened; it counts


def test_every_build_is_logged_to_stdout_and_a_file(monkeypatch, tmp_path, capsys):
    log = tmp_path / "builds.jsonl"
    monkeypatch.setattr(main, "LOG_FILE", str(log))
    long_prompt = "revenue by month " + "x" * 500
    client.post("/build", headers=token("manager", "logged"), json={"prompt": long_prompt})
    client.post("/build", headers=token("rep", "logged-rep"), json={"prompt": "profit by region"})
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(e["user"], e["role"], e["status"], e["mode"]) for e in lines] == [("logged", "manager", "ok", "standin"), ("logged-rep", "rep", "cannot", "standin")]
    assert len(lines[0]["prompt"]) == 160 and lines[0]["at"].endswith("+00:00") and lines[0]["usage"]["turns"] == 1 and lines[0]["refine"] is False
    assert '"event": "build"' in capsys.readouterr().out


def test_a_log_file_that_cannot_be_written_does_not_break_a_build(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "LOG_FILE", str(tmp_path / "missing-dir" / "builds.jsonl"))
    assert client.post("/build", headers=token(user="unlogged"), json={"prompt": "revenue by month"}).status_code == 200


def test_control_characters_are_removed_from_the_prompt():
    assert main.clean("revenue\x00 by\x07 month\nand more\tstuff") == "revenue by month\nand more\tstuff"


# ---------------------------------------------------------------------------------------------------------------- saved dashboards over HTTP
@pytest.fixture
def memory_store(monkeypatch):
    from builder.store import MemoryStore
    store = MemoryStore()
    monkeypatch.setattr(main, "STORE", store)
    return store


def sales_yaml(role="manager", user="maker"):
    return client.post("/build", headers=token(role, user), json={"prompt": "monthly revenue by channel and the top 5 products"}).json()["yaml"]


def test_saving_is_off_without_a_database_and_everything_else_still_works(monkeypatch):
    monkeypatch.setattr(main, "STORE", None)
    h = token("manager", "nodb")
    r = client.get("/saved", headers=h)
    assert r.status_code == 503 and "BUILDER_DB_PASSWORD" in r.json()["detail"]
    assert client.get("/info", headers=h).json()["saving"] is False
    assert client.post("/build", headers=h, json={"prompt": "revenue by month"}).status_code == 200


def test_the_whole_life_of_a_saved_dashboard(memory_store):
    owner, other, rep = token("manager", "olga"), token("manager", "otto"), token("rep", "rita")
    yml = sales_yaml()
    made = client.post("/saved", headers=owner, json={"yaml": yml, "title": "Olga's sales"})
    assert made.status_code == 201 and made.json()["visibility"] == "private" and made.json()["mine"] and set(made.json()["readable_by"]) >= {"manager", "admin"}
    id_ = made.json()["id"]
    assert client.get("/info", headers=owner).json()["saving"] is True
    assert [d["title"] for d in client.get("/saved", headers=owner).json()] == ["Olga's sales"] and client.get("/saved", headers=other).json() == []
    assert client.get(f"/saved/{id_}", headers=other).status_code == 404
    opened = client.get(f"/saved/{id_}", headers=owner).json()
    assert opened["spec"]["id"] == "draft" and opened["meta"]["can_edit"] and opened["yaml"] and "readable_by" in opened
    shared = client.put(f"/saved/{id_}", headers=owner, json={"visibility": "roles", "shared_roles": ["manager"]})
    assert shared.status_code == 200 and shared.json()["shared_roles"] == ["manager"]
    seen = client.get(f"/saved/{id_}", headers=other).json()
    assert seen["meta"]["owner"] == "olga" and not seen["meta"]["can_edit"] and "readable_by" not in seen
    assert client.get(f"/saved/{id_}", headers=rep).status_code == 404, "shared with managers only"
    assert client.put(f"/saved/{id_}", headers=other, json={"yaml": yml}).status_code == 403
    assert client.delete(f"/saved/{id_}", headers=other).status_code == 403
    assert client.put(f"/saved/{id_}", headers=owner, json={"title": "Renamed", "yaml": yml.replace("Sales dashboard", "Sales v2")}).json()["version"] in (1, 2)
    assert [v["version"] for v in client.get(f"/saved/{id_}/versions", headers=owner).json()][0] >= 1
    assert client.get(f"/saved/{id_}/versions", headers=other).status_code == 403
    assert client.delete(f"/saved/{id_}", headers=owner).status_code == 204
    assert client.get(f"/saved/{id_}", headers=owner).status_code == 404 and client.get("/saved", headers=owner).json() == []


def test_a_role_that_cannot_read_a_shared_dashboard_gets_the_reason(memory_store):
    maker = token("manager", "maker2")
    profit = client.post("/build", headers=maker, json={"prompt": "revenue and profit by month"}).json()["yaml"]
    made = client.post("/saved", headers=maker, json={"yaml": profit, "visibility": "everyone"}).json()
    assert "rep" not in made["readable_by"]
    rita = token("rep", "rita2")
    listed = client.get("/saved", headers=rita).json()
    assert listed[0]["readable"] is False and any("gross_profit" in p for p in listed[0]["problems"])
    r = client.get(f"/saved/{made['id']}", headers=rita)
    assert r.status_code == 422 and "cannot open" in r.json()["detail"]["message"] and any("role 'rep' cannot read" in p for p in r.json()["detail"]["problems"])


def test_saving_checks_the_file_for_the_savers_role_and_the_input(memory_store):
    rep = token("rep", "rita3")
    manager_yaml = client.post("/build", headers=token("manager", "m3"), json={"prompt": "revenue and profit by month"}).json()["yaml"]
    r = client.post("/saved", headers=rep, json={"yaml": manager_yaml})
    assert r.status_code == 422 and any("profit" in p for p in r.json()["detail"]["problems"])
    h = token("manager", "m4")
    ok = sales_yaml()
    assert client.post("/saved", headers=h, json={"yaml": ""}).status_code == 422
    assert client.post("/saved", headers=h, json={"yaml": ok, "visibility": "world"}).status_code == 422
    assert client.post("/saved", headers=h, json={"yaml": ok, "visibility": "roles"}).status_code == 422
    assert client.post("/saved", headers=h, json={"yaml": ok, "title": "x" * 121}).status_code == 422
    assert client.post("/saved", json={"yaml": ok}).status_code == 401


def test_a_user_can_only_keep_so_many(memory_store, monkeypatch):
    monkeypatch.setattr(main, "MAX_SAVED", 2)
    h, yml = token("manager", "hoarder"), sales_yaml()
    for _ in range(2):
        assert client.post("/saved", headers=h, json={"yaml": yml}).status_code == 201
    r = client.post("/saved", headers=h, json={"yaml": yml})
    assert r.status_code == 409 and "delete one first" in r.json()["detail"]


def test_saves_changes_and_deletions_are_logged(memory_store, monkeypatch, tmp_path):
    log = tmp_path / "log.jsonl"
    monkeypatch.setattr(main, "LOG_FILE", str(log))
    h = token("manager", "logger")
    id_ = client.post("/saved", headers=h, json={"yaml": sales_yaml(), "visibility": "everyone"}).json()["id"]
    client.put(f"/saved/{id_}", headers=h, json={"visibility": "private"})
    client.delete(f"/saved/{id_}", headers=h)
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert [e["event"] for e in events if e["user"] == "logger"][-3:] == ["saved", "saved_update", "saved_delete"]
    assert next(e for e in events if e["event"] == "saved")["visibility"] == "everyone"
