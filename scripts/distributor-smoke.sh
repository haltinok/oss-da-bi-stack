#!/usr/bin/env bash
# Smoke test of the distributor stack (docker-compose.distributor.yml): signs in as admin and checks that Cube answers from Postgres, the dashboards are the model's, and the builder,
# the SQL lab and the admin console know the model and no AdventureWorks name appears. Needs the stack up and .env; the ports are the ones the stack was started with.
#   KEYCLOAK_PORT=28180 AUTH_PORT=28200 CUBE_PORT=24000 DASHBOARD_CUBE_PORT=28250 BUILDER_PORT=28350 ADMIN_PORT=28400 LAB_PORT=28450 scripts/distributor-smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."
# .env fills in what is not already set (so the ports given on the command line win)
while IFS= read -r line; do [[ "$line" =~ ^([A-Z_0-9]+)=(.*)$ ]] && [ -z "${!BASH_REMATCH[1]+x}" ] && export "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"; done < .env
K=http://localhost:${KEYCLOAK_PORT:-8180}; A=http://localhost:${AUTH_PORT:-8200}; C=http://localhost:${CUBE_PORT:-4000}; D=http://localhost:${DASHBOARD_CUBE_PORT:-8250}
B=http://localhost:${BUILDER_PORT:-8350}; M=http://localhost:${ADMIN_PORT:-8400}; L=http://localhost:${LAB_PORT:-8450}
ok() { echo "ok   $1"; }; fail() { echo "FAIL $1" >&2; exit 1; }
AW='internet_sales|reseller_sales|inventory_health|offer_performance|AdventureWorks|territories'

kc=$(curl -sf -X POST $K/realms/spike/protocol/openid-connect/token -d grant_type=password -d client_id=dashboard -d username=admin -d "password=$TEST_USER_PASSWORD" | jq -r .access_token)
[ -n "$kc" ] && [ "$kc" != null ] || fail "sign in (is the password grant on? see docs/deploy-demo.md)"; ok "signed in as admin"
session=$(curl -sf -X POST $A/token -H "Authorization: Bearer $kc"); cube=$(echo "$session" | jq -r .token)
[ "$(echo "$session" | jq -r '.rls | keys | join(",")')" = "dealer_region" ] || fail "the token's row-level dimensions are the distributor's: $(echo "$session" | jq -c .rls)"; ok "the auth service mints a Cube token with the distributor's row-level dimension"

meta=$(curl -sf -H "Authorization: $cube" $C/cubejs-api/v1/meta)
echo "$meta" | jq -e '[.cubes[].name] | contains(["orders","payments","dealers","items","calendar"])' >/dev/null || fail "Cube's cubes"; ok "Cube serves the distributor's cubes"
echo "$meta" | grep -qE "$AW" && fail "Cube's meta names an AdventureWorks cube" || ok "no AdventureWorks name in Cube's meta"
rev=$(curl -sf -G -H "Authorization: $cube" $C/cubejs-api/v1/load --data-urlencode 'query={"measures":["orders.revenue","orders.order_count"],"dimensions":["dealers.region"],"order":{"orders.revenue":"desc"},"limit":3}' | jq -r '.data[0]["orders.revenue"]')
[ -n "$rev" ] && [ "$rev" != null ] || fail "a query through Cube on Postgres"; ok "a query through Cube on Postgres: top region revenue $rev"
code=$(curl -s -o /dev/null -w '%{http_code}' -G -H "Authorization: $cube" $C/cubejs-api/v1/load --data-urlencode 'query={"measures":["internet_sales.revenue"]}'); [ "$code" != 200 ] || fail "an AdventureWorks cube answered"; ok "an AdventureWorks cube does not exist here ($code)"

[ "$(curl -s -o /dev/null -w '%{http_code}' $D/)" = 302 ] && [ "$(curl -s -o /dev/null -w '%{http_code}' $D/home/)" = 200 ] || fail "the start page"; ok "the start page is served"
idx=$(curl -sf $D/dashboards/index.json); echo "$idx" | jq -e '[.[].id] | sort == ["collections","distributor-overview"]' >/dev/null || fail "the dashboards list: $(echo "$idx" | jq -c '[.[].id]')"; ok "the dashboards are the distributor's"
curl -sf $D/dashboards/distributor-overview.json | jq -e '.panels | length > 3' >/dev/null || fail "a compiled dashboard"; ok "a compiled dashboard is served"

info=$(curl -sf -H "Authorization: Bearer $kc" $B/info); echo "$info" | grep -qE "$AW" && fail "the builder's page text names an AdventureWorks cube: $(echo "$info" | jq -c .examples)"
echo "$info" | jq -e '.examples | length > 0 and all(.[]; test("channel|Internet|Reseller|product"; "i") | not)' >/dev/null || fail "the builder's suggestions are another model's: $(echo "$info" | jq -c .examples)"; ok "the builder's suggestions are made for this model: $(echo "$info" | jq -r '.examples[0]')"
built=$(curl -sf -X POST -H "Authorization: Bearer $kc" -H 'Content-Type: application/json' -d '{"prompt":"revenue by region"}' $B/build); echo "$built" | jq -e '.ok == true or (.yaml | length > 0)' >/dev/null || fail "a build: $(echo "$built" | head -c 300)"; ok "the builder builds a dashboard from a request on this model"
sch=$(curl -sf -H "Authorization: Bearer $kc" $L/schema); echo "$sch" | jq -e '[.cubes[].name] | contains(["orders","dealers"])' >/dev/null || fail "the lab's schema"; echo "$sch" | grep -qE "$AW" && fail "the lab's schema names an AdventureWorks cube"; ok "the SQL lab lists the distributor's cubes and examples: $(echo "$sch" | jq -r '.examples[0].sql' | head -1)"
dims=$(curl -sf -H "Authorization: Bearer $kc" $M/rls/rules); echo "$dims" | grep -qE "$AW|Bikes|Canada" && fail "the admin console shows AdventureWorks rules"; ok "the admin console reads the distributor's row rules"
echo "distributor stack checks passed"
