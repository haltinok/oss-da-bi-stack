"""The HTTP service: who may call it, what each role sees, the rate limit, the modes, and a build end to end (no Keycloak, no model API)."""
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
