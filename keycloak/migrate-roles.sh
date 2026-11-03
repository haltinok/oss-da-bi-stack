#!/usr/bin/env bash
# One-time move from the old roles to capability roles (PLAN: roles say what a person may DO; data access comes from groups, datasets and row rules).
#
#   admin                 stays admin
#   manager               -> editor + group Managers
#   rep                   -> editor + group Reps
#   purchasing            -> editor + group Purchasing
#   marketing             -> editor + group Marketing
#   viewer                stays viewer
#
# The groups carry the data access the old roles had: run postgres/sync-access.sh first (it seeds the matching datasets and grants), and run this BEFORE restarting the auth service
# with the new code, because the new auth service no longer recognises the old roles (a person who only has one is refused until moved). Idempotent; the old roles are removed at the end,
# once nobody holds them.
#
#   keycloak/migrate-roles.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . "${ENV_FILE:-./.env}"; set +a
. keycloak/lib.sh
kc_login

for role in editor viewer; do kc create roles -r spike -s "name=$role" >/dev/null 2>&1 || true; done
for group in Managers Reps Purchasing Marketing; do kc create groups -r spike -s "name=$group" >/dev/null 2>&1 || true; done
gid() { kc get groups -r spike -q "search=$1" --fields id,name --format csv --noquotes | awk -F, -v n="$1" '$2 == n {print $1; exit}'; }

moved=0
for pair in manager:Managers rep:Reps purchasing:Purchasing marketing:Marketing; do
  old=${pair%%:*}; group=${pair##*:}
  g=$(gid "$group")
  for uid in $(kc get "roles/$old/users" -r spike --fields id --format csv --noquotes 2>/dev/null || true); do
    kc add-roles -r spike --uid "$uid" --rolename editor >/dev/null
    kc update "users/$uid/groups/$g" -r spike -s realm=spike -n >/dev/null 2>&1 || true
    kc remove-roles -r spike --uid "$uid" --rolename "$old" >/dev/null 2>&1 || true
    echo "moved a $old to editor + $group ($uid)"; moved=$((moved + 1))
  done
done
for old in manager rep purchasing marketing; do
  if [ -z "$(kc get "roles/$old/users" -r spike --fields id --format csv --noquotes 2>/dev/null || true)" ]; then
    kc delete "roles/$old" -r spike >/dev/null 2>&1 && echo "role $old: removed" || true
  else
    echo "role $old: still held by someone, kept"
  fi
done
echo "done: $moved people moved"
