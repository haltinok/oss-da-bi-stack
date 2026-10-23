#!/usr/bin/env bash
# Point the `dashboard` client of an existing Keycloak at PUBLIC_URL: redirect URIs, web origins and post-logout redirect URIs.
#
# Keycloak imports keycloak/realm-spike.json only when the realm does not exist yet, so on a volume that already holds the
# realm (a server that ran with localhost URLs first, or a PUBLIC_URL that changed) those values stay as they were and login
# ends in "Invalid parameter: redirect_uri". A fresh volume needs nothing: the import reads PUBLIC_URL.
#
# In a public deployment (PUBLIC_URL not http://localhost...) it also turns off the dashboard client's direct password grant
# (and turns it back on when PUBLIC_URL is a localhost address again):
# the browser uses the authorization-code flow with PKCE; the grant exists only so the tests can log in headlessly, and on the
# internet it would be an API for guessing passwords. Pass --keep-password-grant to leave it on (the security and browser
# tests need it, so run those against a local stack or before the switch).
#
#   keycloak/update-public-url.sh [--keep-password-grant]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . "${ENV_FILE:-./.env}"; set +a
. keycloak/lib.sh

url=$(public_url)
kc_login
cid=$(kc get clients -r spike -q clientId=dashboard --fields id --format csv --noquotes)
[ -n "$cid" ] || { echo "no client 'dashboard' in realm spike: has the realm been imported?" >&2; exit 1; }

args=(-s "redirectUris=[\"$url/*\"]" -s "webOrigins=[\"$url\"]" -s "attributes.\"post.logout.redirect.uris\"=$url/*")
if is_public; then
  if [ "${1:-}" != "--keep-password-grant" ]; then
    args+=(-s directAccessGrantsEnabled=false)
    echo "direct password grant: off (public deployment)"
  fi
else
  args+=(-s directAccessGrantsEnabled=true)      # back to a local run: the tests log in headlessly with it
  echo "direct password grant: on (local)"
fi
kc update "clients/$cid" -r spike "${args[@]}"
echo "dashboard client now allows $url/*"
kc get "clients/$cid" -r spike | grep -E -A1 '"(redirectUris|webOrigins)"|directAccessGrantsEnabled|post.logout.redirect.uris|pkce.code.challenge.method' | grep -v '^--$'
