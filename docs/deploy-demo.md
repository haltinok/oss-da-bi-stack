# Serving the demo at https://demo.eloha-da.com

The `starrocks` profile normally listens on `127.0.0.1` only. For a demo anyone can open in a browser, a public overlay
adds one front door: **Caddy** gets a Let's Encrypt certificate and routes by path, and the other services keep their
ports on `127.0.0.1`.

```
https://demo.eloha-da.com
  /kc/*            Keycloak       (sign-in; KC_HTTP_RELATIVE_PATH=/kc; the admin console and master realm answer 404)
  /auth-api/*      auth service   (Keycloak token -> Cube token)       prefix stripped
  /actions-api/*   actions service (approve inventory actions)         prefix stripped
  /cubejs-api/*    Cube           (queries; every call needs the signed token)
  everything else  dashboard-cube (the page)
```

Everything mode-specific lives in `docker-compose.public.yml`, so a local run (`docker-compose.yml` alone, `PUBLIC_URL` unset)
is unchanged. `PUBLIC_URL` is the one setting: the browser configuration (`dashboard/cube/nginx.conf.template`), the auth and
actions services' issuer and allowed origins, Keycloak's hostname and the realm's redirect URIs, web origins and post-logout
URIs all derive from it.

## What you need first
- A server with Docker and the compose plugin (the Contabo box: 12 vCPU, 48 GB; the 250M tier needs `STARROCKS_MEM_LIMIT=38g`, the
  live demo alone about 16 GB).
- The DNS A record `demo.eloha-da.com` -> the server's public IP, **DNS only** (not proxied: Let's Encrypt must reach the server).
- Ports **80 and 443** reachable from the internet and not used by anything else on the server (`sudo ss -ltnp | grep -E ':(80|443) '`
  must be empty).

## Deploy (fresh server)
```bash
git clone https://github.com/haltinok/oss-da-bi-stack && cd oss-da-bi-stack
./scripts/generate-env.sh                                   # random secrets into .env (mode 0600)
cat >> .env <<'EOT'
PUBLIC_URL=https://demo.eloha-da.com
COMPOSE_FILE=docker-compose.yml:docker-compose.public.yml
STARROCKS_MEM_LIMIT=16g
EOT
# optional dry run without Let's Encrypt rate limits (browsers will not trust that certificate):
#   echo 'ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory' >> .env
docker compose --profile starrocks up -d --build            # COMPOSE_FILE adds Caddy; plain `docker compose` commands now use it
docker compose logs -f caddy                                # "certificate obtained successfully" within a minute
```
Then fill the data: unpause the two DAGs in Airflow (`http://localhost:8080` through `ssh -L 8080:localhost:8080 demo`):
`simulate_adventureworks` and `postgres_active_to_starrocks` (the second builds the mart in about a minute and refreshes it
every 5 minutes). For the weekly proposal agent also unpause `inventory_weekly_proposals`.

The demo users (`admin`, `na_manager`, `de_rep`, `buyer`, `marketer`) all use `TEST_USER_PASSWORD` from `.env`.

## Check it
```bash
curl -sI https://demo.eloha-da.com/ | head -1                                              # HTTP/2 200
curl -s https://demo.eloha-da.com/kc/realms/spike/.well-known/openid-configuration | jq -r .issuer   # https://demo.eloha-da.com/kc/realms/spike
curl -s -o /dev/null -w '%{http_code}\n' https://demo.eloha-da.com/kc/admin/                # 404 (the admin console is not public)
curl -s -o /dev/null -w '%{http_code}\n' https://demo.eloha-da.com/cubejs-api/v1/meta       # 401 (no token)
curl -s -o /dev/null -w '%{http_code}\n' http://demo.eloha-da.com/                          # 308 to https
```
Then open `https://demo.eloha-da.com/` and sign in. The browser contacts only that one host.

## An existing Keycloak volume (a server that ran with localhost first, or a PUBLIC_URL that changed)
Keycloak imports `keycloak/realm-spike.json` only when the realm does not exist yet, so on a volume that already holds it the
redirect URIs stay at the old address and login fails with *Invalid parameter: redirect_uri*. After setting `PUBLIC_URL` and
`COMPOSE_FILE` in `.env` and recreating Keycloak (`docker compose up -d keycloak`, which now serves under `/kc`):
```bash
keycloak/update-public-url.sh        # redirect URIs, web origins, post-logout URIs -> PUBLIC_URL; direct password grant off
keycloak/sync-users.sh               # only if the roles / users added since the volume was created are missing
```
`update-public-url.sh` is idempotent. On a public host it also turns off the dashboard client's direct password grant (the browser
uses the authorization-code flow with PKCE; the grant exists for headless tests and on the internet it is a password-guessing API).
`--keep-password-grant` leaves it on. The security and browser tests (`cube/tests`, `dashboard/cube/tests/e2e.py`) use that grant:
run them on a local stack, or against the server before the script, or with the flag.

## Things to know
- **Certificates.** Caddy keeps them in the `caddy_data` volume: do not delete it (Let's Encrypt limits re-issuing). Renewal is automatic.
  If issuance fails, `docker compose logs caddy` says why (DNS not pointing here, port 80 or 443 blocked, the DNS record proxied).
- **Only Caddy publishes ports.** `docker compose ps` / `docker compose config | grep -B1 published` show 80 and 443 on `0.0.0.0` and
  everything else on `127.0.0.1`. Airflow, StarRocks and the databases are reached through `ssh -L`.
- **The Dataset switch** (live / 250M benchmark) is not offered on a public host: the benchmark Cube is published on the server's
  localhost only.
- **Keycloak admin.** The admin console is blocked at the proxy. Administer with `docker compose exec keycloak /opt/keycloak/bin/kcadm.sh`
  (what the scripts do), or temporarily through `ssh -L 8180:localhost:8180 demo` (the console then redirects to the public host, so
  prefer `kcadm.sh`).
- **After a reboot.** If StarRocks' frontend stays unhealthy (`docker compose logs starrocks-fe` repeats *wait globalStateMgr to be
  ready, FE type: INIT*), its node was registered under the container's old IP and Docker handed out a different one. This is a
  known problem of the compose setup, not of this overlay, and it is not solved here.
- **Demo posture.** Keycloak is `start-dev` (embedded H2) behind TLS, data is simulated, the user passwords are demo passwords.
  Do not put customer or bank data on it. See `SECURITY.md`.
- **Local test of the overlay** (no domain needed): `PUBLIC_URL=http://localhost:8088` with an override that publishes Caddy's port 8088
  serves everything on plain HTTP through the same routes; the CI job `public-routing` does exactly that.

## Back to local-only
Remove the `COMPOSE_FILE` and `PUBLIC_URL` lines from `.env` and `docker compose up -d`. A Keycloak volume that was switched to the
public address keeps the public redirect URIs: run `PUBLIC_URL=http://localhost:8250 keycloak/update-public-url.sh` (any
`http://localhost` value counts as local, and the script then turns the password grant back on) after the stack is back up.
