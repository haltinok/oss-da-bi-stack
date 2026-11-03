#!/usr/bin/env bash
# Add the roles and users that keycloak/realm-spike.json defines to a Keycloak that already imported the
# realm. `--import-realm` only runs when the realm does not exist yet, so an existing Keycloak volume keeps
# its old users and misses later additions (here: the editor and viewer roles, the data-access groups, the buyer and
# marketer users, and the proposal agent's `inventory-agent` client and `agent` role). Idempotent; nothing is deleted or overwritten (except duplicate client mappers, see kc_dedupe_mappers in lib.sh). Reads secrets from .env.
#
#   keycloak/sync-users.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . "${ENV_FILE:-./.env}"; set +a
. keycloak/lib.sh
kc_login

# A role says what a person may DO (admin, editor, viewer; `agent` is the proposal agent's). What data they read comes from groups, datasets and row rules (the admin console).
for role in editor viewer agent; do
  kc create roles -r spike -s "name=$role" >/dev/null 2>&1 && echo "role $role: created" || echo "role $role: exists"
done
for group in Managers Reps Purchasing Marketing; do
  kc create groups -r spike -s "name=$group" >/dev/null 2>&1 && echo "group $group: created" || echo "group $group: exists"
done
for pair in buyer:Purchasing marketer:Marketing; do
  user=${pair%%:*}; group=${pair##*:}
  if [ -n "$(kc get users -r spike -q "username=$user" --fields id --format csv --noquotes)" ]; then
    echo "user $user: exists"
  else
    kc create users -r spike -s "username=$user" -s enabled=true -s emailVerified=true \
      -s "email=$user@spike.local" -s "firstName=${user^^}" -s lastName=Spike >/dev/null
    kc set-password -r spike --username "$user" --new-password "${TEST_USER_PASSWORD:?}" >/dev/null
    kc add-roles -r spike --uusername "$user" --rolename editor >/dev/null
    gid=$(kc get groups -r spike -q "search=$group" --fields id --format csv --noquotes | head -1)
    uid=$(kc get users -r spike -q "username=$user" --fields id --format csv --noquotes)
    kc update "users/$uid/groups/$gid" -r spike -s realm=spike -n >/dev/null 2>&1 || true
    echo "user $user: created as editor in the $group group"
  fi
done

# The proposal agent: a confidential client with a service account that holds only the `agent` role.
cid=$(kc get clients -r spike -q clientId=inventory-agent --fields id --format csv --noquotes)
if [ -z "$cid" ]; then
  kc create clients -r spike -s clientId=inventory-agent -s publicClient=false -s serviceAccountsEnabled=true \
    -s standardFlowEnabled=false -s directAccessGrantsEnabled=false -s "secret=${AGENT_CLIENT_SECRET:?}" >/dev/null
  echo "client inventory-agent: created"
else
  kc_dedupe_mappers "$cid" inventory-agent
  kc update "clients/$cid" -r spike -s "secret=${AGENT_CLIENT_SECRET:?}" >/dev/null
  echo "client inventory-agent: exists (secret refreshed)"
fi
kc add-roles -r spike --uusername service-account-inventory-agent --rolename agent >/dev/null 2>&1 && echo "service account: agent role set" || echo "service account: role not set"

# The admin console: a confidential client whose service account may manage users and groups (and nothing else of the realm).
cid=$(kc get clients -r spike -q clientId=admin-console --fields id --format csv --noquotes)
if [ -z "$cid" ]; then
  kc create clients -r spike -s clientId=admin-console -s publicClient=false -s serviceAccountsEnabled=true \
    -s standardFlowEnabled=false -s directAccessGrantsEnabled=false -s "secret=${ADMIN_CLIENT_SECRET:?}" >/dev/null
  echo "client admin-console: created"
else
  kc_dedupe_mappers "$cid" admin-console
  kc update "clients/$cid" -r spike -s "secret=${ADMIN_CLIENT_SECRET:?}" >/dev/null
  echo "client admin-console: exists (secret refreshed)"
fi
for role in manage-users view-users query-users query-groups view-realm; do
  kc add-roles -r spike --uusername service-account-admin-console --cclientid realm-management --rolename "$role" >/dev/null 2>&1 || true
done
echo "service account: realm-management roles set"

# The groups a person belongs to travel in the access token (claim `groups`), which the auth service passes on in the Cube token.
dash=$(kc get clients -r spike -q clientId=dashboard --fields id --format csv --noquotes)
if kc get "clients/$dash/protocol-mappers/models" -r spike --fields name --format csv --noquotes | grep -qx groups; then
  echo "mapper groups: exists"
else
  kc create "clients/$dash/protocol-mappers/models" -r spike -s name=groups -s protocol=openid-connect -s protocolMapper=oidc-group-membership-mapper \
    -s 'config."claim.name"=groups' -s 'config."full.path"=false' -s 'config."id.token.claim"=true' -s 'config."access.token.claim"=true' -s 'config."userinfo.token.claim"=true' >/dev/null
  echo "mapper groups: created"
fi
