"""Row-level security + auth tests against the live spike stack (Phase 5).

  set -a; . ./.env.spike; set +a
  uv run --with pytest --with requests --with pymysql --with pyjwt python -I -m pytest spike/cube/tests -v

Users (Keycloak realm `spike`, territories from dbt seed dim_user_territory):
  admin       all territories, everything
  na_manager  North America group (6 regions), no customer data
  de_rep      Germany only, no gross profit / margin / cost
Ground truth is direct SQL on the mart, filtered to the user's territories.
"""
import base64
import json
import os
import time
from decimal import Decimal

import jwt
import pymysql
import pytest
import requests

KEYCLOAK = os.environ.get("KEYCLOAK_URL", "http://localhost:8180")
AUTH = os.environ.get("AUTH_URL", "http://localhost:8200")
CUBE = os.environ.get("CUBE_URL", "http://localhost:4000/cubejs-api/v1/load")
SECRET = os.environ["CUBEJS_API_SECRET"]
PASSWORD = os.environ["TEST_USER_PASSWORD"]
LIVE = "order_status NOT IN (4, 6)"
TOL = Decimal("0.05")

REGIONS = {
    "admin": {"Australia", "Canada", "Central", "France", "Germany", "Northeast", "Northwest", "Southeast", "Southwest", "United Kingdom"},
    "na_manager": {"Canada", "Central", "Northeast", "Northwest", "Southeast", "Southwest"},
    "de_rep": {"Germany"},
}


def sql(q):
    with pymysql.connect(host="127.0.0.1", port=int(os.environ.get("STARROCKS_MYSQL_PORT", "9030")), user="root",
                         read_timeout=3600).cursor() as cur:
        cur.execute(q)
        return cur.fetchall()


def cube_token(user):
    kc = requests.post(f"{KEYCLOAK}/realms/spike/protocol/openid-connect/token", timeout=30,
                       data={"grant_type": "password", "client_id": "dashboard", "username": user, "password": PASSWORD})
    kc.raise_for_status()
    r = requests.post(f"{AUTH}/token", headers={"Authorization": f"Bearer {kc.json()['access_token']}"}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


class Token(str):
    """A Cube token that knows whose it is, so load() can renew it if it expired mid-test."""
    user = None


class Tokens:
    """Cube tokens per user, re-minted when older than 8 minutes (they live 15)."""

    def __init__(self):
        self._t = {}

    def __getitem__(self, user):
        tok, at = self._t.get(user, (None, 0))
        if time.time() - at > 480:
            tok = Token(cube_token(user))
            tok.user = user
            self._t[user] = (tok, time.time())
        return tok


@pytest.fixture(scope="session")
def tokens():
    return Tokens()


def load(query, token):
    """POST a Cube query; returns (status, json). Waits out 'Continue wait'."""
    renewed = False
    while True:
        headers = {"Authorization": token} if token is not None else {}
        r = requests.post(CUBE, json={"query": query}, headers=headers, timeout=1800)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if body.get("error") == "Continue wait":
            time.sleep(1)
            continue
        if r.status_code == 401 and isinstance(token, Token) and not renewed:
            user = token.user                                       # a legit token that outlived its 15 min
            token = Token(cube_token(user))
            token.user, renewed = user, True
            continue
        return r.status_code, body


def rejected(status, body):
    """Refused with 401/403, no data, and no stack trace leaked."""
    return status in (401, 403) and "data" not in body and "stack" not in body


def near(a, b):
    return abs(Decimal(str(a)) - Decimal(str(b))) <= TOL


def regions_sql(user):
    return "(" + ",".join(f"'{r}'" for r in sorted(REGIONS[user])) + ")"


# --- totals per user = direct SQL filtered to their territories ----------------------------

@pytest.mark.parametrize("user", list(REGIONS))
@pytest.mark.parametrize("channel", ["internet", "reseller"])
def test_totals_match_sql_for_user_territories(tokens, user, channel):
    status, body = load({"measures": [f"{channel}_sales.revenue", f"{channel}_sales.units"]}, tokens[user])
    assert status == 200, body
    (rev, units), = sql(
        f"select sum(f.sales_amount), sum(f.order_quantity) from mart.fact_{channel}_sales f "
        f"join mart.dim_sales_territory t on t.sales_territory_key = f.sales_territory_key "
        f"where {LIVE} and t.sales_territory_region in {regions_sql(user)}")
    row = body["data"][0]
    assert near(row[f"{channel}_sales.revenue"], rev)
    assert int(row[f"{channel}_sales.units"]) == int(units)


@pytest.mark.parametrize("user", list(REGIONS))
def test_every_visual_only_shows_own_territories(tokens, user):
    tok, allowed = tokens[user], REGIONS[user]
    # territory dropdown
    status, body = load({"dimensions": ["territories.region", "territories.group_name"]}, tok)
    assert status == 200 and {d["territories.region"] for d in body["data"]} == allowed
    # revenue by region (territories panel), both channels
    for ch in ("internet", "reseller"):
        status, body = load({"measures": [f"{ch}_sales.revenue"], "dimensions": ["territories.region"]}, tok)
        assert status == 200 and {d["territories.region"] for d in body["data"]} <= allowed
    # monthly orders panel (count_distinct rollups): every month listed belongs to allowed regions only
    status, body = load({"measures": ["internet_sales.orders"], "dimensions": ["territories.region"],
                         "timeDimensions": [{"dimension": "internet_sales.order_date", "granularity": "month"}]}, tok)
    assert status == 200 and {d["territories.region"] for d in body["data"]} <= allowed
    # latest-orders list, queried like the dashboard: newest day first, then that last week only
    status, body = load({"measures": ["internet_sales.revenue"], "timeDimensions": [
        {"dimension": "internet_sales.order_date", "granularity": "day"}], "order": {"internet_sales.order_date": "desc"}, "limit": 1}, tok)
    assert status == 200 and body["data"]
    end = body["data"][0]["internet_sales.order_date.day"][:10]
    status, body = load({"measures": ["internet_sales.lines"],
                         "dimensions": ["internet_sales.order_number", "internet_sales.order_date", "territories.region"],
                         "timeDimensions": [{"dimension": "internet_sales.order_date", "dateRange": [end, end]}],
                         "order": {"internet_sales.order_date": "desc"}, "limit": 8}, tok)
    assert status == 200 and body["data"] and {d["territories.region"] for d in body["data"]} <= allowed


def test_reference_dropdowns_work_for_everyone(tokens):
    for user in REGIONS:
        status, body = load({"dimensions": ["products.category", "products.subcategory"]}, tokens[user])
        assert status == 200 and body["data"], user
        status, body = load({"dimensions": ["dates.fiscal_year"]}, tokens[user])
        assert status == 200 and body["data"], user


# --- tampering with the request cannot widen access -------------------------------------

def test_requesting_another_region_returns_nothing(tokens):
    status, body = load({"measures": ["internet_sales.revenue"], "dimensions": ["territories.region"],
                         "filters": [{"member": "territories.region", "operator": "equals", "values": ["Northwest"]}]}, tokens["de_rep"])
    assert status == 200 and body["data"] == []


def test_or_filter_cannot_widen(tokens):
    status, body = load({"measures": ["internet_sales.revenue"], "dimensions": ["territories.region"], "filters": [
        {"or": [{"member": "territories.region", "operator": "equals", "values": ["Germany"]},
                {"member": "territories.region", "operator": "equals", "values": ["Northwest"]}]}]}, tokens["de_rep"])
    assert status == 200 and {d["territories.region"] for d in body["data"]} == {"Germany"}


def test_not_equals_cannot_widen(tokens):
    status, body = load({"measures": ["internet_sales.revenue"], "dimensions": ["territories.region"],
                         "filters": [{"member": "territories.region", "operator": "notEquals", "values": ["Germany"]}]}, tokens["de_rep"])
    assert status == 200 and body["data"] == []


def test_manager_cannot_see_europe(tokens):
    status, body = load({"measures": ["reseller_sales.revenue"], "dimensions": ["territories.group_name"]}, tokens["na_manager"])
    assert status == 200 and {d["territories.group_name"] for d in body["data"]} == {"North America"}


@pytest.mark.parametrize("member", ["gross_profit", "margin_pct", "product_cost"])
def test_rep_cannot_request_profit_members(tokens, member):
    status, body = load({"measures": [f"internet_sales.{member}"]}, tokens["de_rep"])
    assert rejected(status, body), (status, body)


def test_rep_cannot_hide_profit_in_a_filter_or_order(tokens):
    status, body = load({"measures": ["internet_sales.revenue"], "order": {"internet_sales.gross_profit": "desc"}}, tokens["de_rep"])
    assert rejected(status, body), (status, body)


def test_manager_can_see_profit(tokens):
    status, body = load({"measures": ["internet_sales.gross_profit", "internet_sales.margin_pct"]}, tokens["na_manager"])
    assert status == 200 and body["data"], body


def test_customer_data_is_admin_only(tokens):
    for user in ("na_manager", "de_rep"):
        status, body = load({"measures": ["customers.count"]}, tokens[user])
        assert rejected(status, body), user
        status, body = load({"measures": ["internet_sales.revenue"], "dimensions": ["customers.last_name"], "limit": 1}, tokens[user])
        assert rejected(status, body), user
    status, body = load({"measures": ["customers.count"]}, tokens["admin"])
    assert status == 200 and int(body["data"][0]["customers.count"]) > 0


# --- authentication failures ----------------------------------------------------------

QUERY = {"measures": ["internet_sales.revenue"]}


def test_no_token_rejected():
    assert rejected(*load(QUERY, None))


def test_garbage_token_rejected():
    assert rejected(*load(QUERY, "not-a-jwt"))


def test_expired_token_rejected():
    now = int(time.time())
    tok = jwt.encode({"user_id": "admin", "role": "admin", "territories": [], "iat": now - 7200, "exp": now - 3600}, SECRET, algorithm="HS256")
    assert rejected(*load(QUERY, tok))


def test_token_signed_with_wrong_secret_rejected():
    tok = jwt.encode({"user_id": "admin", "role": "admin", "exp": int(time.time()) + 600}, "not-the-secret", algorithm="HS256")
    assert rejected(*load(QUERY, tok))


def test_tampered_claims_rejected(tokens):
    head, payload, sig = tokens["de_rep"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims.update(role="admin", territories=sorted(REGIONS["admin"]))
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    assert rejected(*load(QUERY, f"{head}.{forged}.{sig}"))


def test_alg_none_rejected():
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    tok = f"{seg({'alg': 'none', 'typ': 'JWT'})}.{seg({'user_id': 'admin', 'role': 'admin', 'exp': int(time.time()) + 600})}."
    assert rejected(*load(QUERY, tok))


def test_token_without_role_rejected():
    tok = jwt.encode({"user_id": "x", "exp": int(time.time()) + 600}, SECRET, algorithm="HS256")
    assert rejected(*load(QUERY, tok))


def test_non_admin_token_with_no_territories_rejected():
    tok = jwt.encode({"user_id": "x", "role": "manager", "territories": [], "exp": int(time.time()) + 600}, SECRET, algorithm="HS256")
    assert rejected(*load(QUERY, tok))


def test_auth_service_rejects_bad_keycloak_tokens():
    assert requests.post(f"{AUTH}/token", timeout=10).status_code == 401
    assert requests.post(f"{AUTH}/token", headers={"Authorization": "Bearer junk"}, timeout=10).status_code == 401
    # a token signed by someone else, with the right claims
    forged = jwt.encode({"iss": f"{KEYCLOAK}/realms/spike", "azp": "dashboard", "preferred_username": "admin",
                         "realm_access": {"roles": ["admin"]}, "exp": int(time.time()) + 600}, "x" * 32, algorithm="HS256")
    assert requests.post(f"{AUTH}/token", headers={"Authorization": f"Bearer {forged}"}, timeout=10).status_code == 401
