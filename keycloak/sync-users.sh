#!/usr/bin/env bash
# Add the roles and users that keycloak/realm-spike.json defines to a Keycloak that already imported the
# realm. `--import-realm` only runs when the realm does not exist yet, so an existing Keycloak volume keeps
# its old users and misses later additions (here: the purchasing and marketing roles and the buyer and
# marketer users). Idempotent; nothing is deleted or overwritten. Reads secrets from .env.
#
#   keycloak/sync-users.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
kc() { docker compose --profile starrocks exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@"; }

kc config credentials --server http://localhost:8080 --realm master \
  --user "${KEYCLOAK_ADMIN:-admin}" --password "${KEYCLOAK_ADMIN_PASSWORD:?}" >/dev/null

for role in purchasing marketing; do
  kc create roles -r spike -s "name=$role" >/dev/null 2>&1 && echo "role $role: created" || echo "role $role: exists"
done
for pair in buyer:purchasing marketer:marketing; do
  user=${pair%%:*}; role=${pair##*:}
  if [ -n "$(kc get users -r spike -q "username=$user" --fields id --format csv --noquotes)" ]; then
    echo "user $user: exists"
  else
    kc create users -r spike -s "username=$user" -s enabled=true -s emailVerified=true \
      -s "email=$user@spike.local" -s "firstName=${user^^}" -s lastName=Spike >/dev/null
    kc set-password -r spike --username "$user" --new-password "${TEST_USER_PASSWORD:?}" >/dev/null
    kc add-roles -r spike --uusername "$user" --rolename "$role" >/dev/null
    echo "user $user: created with role $role"
  fi
done
