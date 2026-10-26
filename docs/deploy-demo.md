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

## Serving the 250M dataset (`DATASET`)

`DATASET` in `.env` chooses what the deployment serves: `live` (the default: the live mart, fed by the simulator and the 5-minute
pipeline), `250m` (only the 250M tier, built into `mart_250m`, `rls_250m` and `adventureworks_dwh_250m` by the steps in
`spike/README.md`) or `both` (the live mart and the 250M tier, with a **Dataset switch in the page header**; see below). What
`live` and `250m` change:

| Service | `DATASET=live` | `DATASET=250m` |
|---|---|---|
| Cube | `cube/model` on `mart`, rollups in `dev_pre_aggregations` | the 500M-tuned model (`spike/cube/model`: year-partitioned incremental rollups, hourly refresh) plus the two inventory cubes, read from `mart_250m`, rollups in their **own** schema `dev_pre_aggregations_250m` |
| auth | territories from `rls.user_regions` | from `rls_250m.user_regions` |
| actions | reads `mart.inventory_health`, writes `postgres_active` | reads `mart_250m.inventory_health` and **refuses every write** (409); the log and proposals are empty |
| dashboard | header badge *Live (simulator)* | header badge *250M benchmark*, a banner, **Approve disabled** with the reason |

Approvals are written to `postgres_active`, which only feeds the live mart (through the simulator and the 5-minute pipeline), so
approving against another dataset would put nonsense into the live ERP: that is why 250m is read-only. The model files are not
copied: `cube/cube.js` loads `spike/cube/model` and re-points `mart.` at `mart_250m.` when it reads them, so the 250m model cannot
drift from the one that was benchmarked.

**Switch to 250m**
```bash
# once, after the 250m dbt build (it makes mart_250m and rls_250m; the stack's read-only users get nothing on them by default):
scripts/grant-dataset.sh 250m
# then:
sed -i 's/^DATASET=.*/DATASET=250m/' .env || echo 'DATASET=250m' >> .env   # set it (replacing an existing line)
docker compose up -d cube auth actions dashboard-cube      # recreate the four services that read it
```
Optionally pause the weekly agent (`inventory_weekly_proposals`): it would read the 250m Cube and its drafts would be refused. (With `both` the agent keeps reading the live Cube.)

**The first rollup build on 250M takes a few minutes.** Cube builds the 250m rollups on the first queries (and then refreshes them
hourly, only the partitions inside the update window). Until a rollup exists the dashboard panels wait (Cube answers "continue
wait"), and the heavy rollups can use several GB of StarRocks memory while they build: do it with the live DAG idle if memory is
tight. Watch `docker compose logs -f cube`; to warm it, open the dashboard once as `admin` and let every panel finish. Later page
loads are served from the rollups (the demo-server benchmark: p95 15-52 ms).

### Both at once: `DATASET=both` (the header switch)
Two Cubes run side by side, from the same model files and the same Cube Store: the usual `cube` (live, rollups in
`dev_pre_aggregations`) and `cube-250m` (the 250M tier on `mart_250m`, rollups in `dev_pre_aggregations_250m`, 127.0.0.1:`CUBE_250M_PORT`,
default 4001), which belongs to the compose profile `dual`. Caddy serves it at `/cubejs-250m/`. The page opens on Live and offers
the switch (`?dataset=250m`, remembered in the browser): Live keeps the full actions flow (Approve, proposals), the 250M dataset is
read-only with a banner that says to switch back to Live to approve. Auth and the actions service stay the live ones (the users and
territories are the same).
```bash
scripts/grant-dataset.sh 250m                       # once, after the 250m dbt build
sed -i 's/^DATASET=.*/DATASET=both/' .env || echo 'DATASET=both' >> .env
docker compose --profile starrocks --profile dual up -d     # starts cube-250m, recreates cube, auth, actions, dashboard-cube
```
Costs: a second Cube container and the 250M rollups next to the live ones in StarRocks and Cube Store. The first 250M query builds
its rollups (a few minutes, as above) while the live 5-minute refresh keeps running, so watch StarRocks memory
(`docker stats`, `STARROCKS_MEM_LIMIT`). Both Cubes use the same `CUBEJS_API_SECRET`, so one sign-in token works for both.
Go back to a single dataset with `DATASET=live`/`250m` and `docker compose --profile starrocks up -d --remove-orphans`.

**Switch back to live**
```bash
sed -i 's/^DATASET=.*/DATASET=live/' .env && docker compose up -d cube auth actions dashboard-cube
```
It is immediate: the live rollups (`dev_pre_aggregations`) were never touched. The 250m ones stay in their schema for the next switch.

Checks: `curl -s https://demo.eloha-da.com/cube/config.js | grep -o 'mart_250m'`; the page header shows the badge; in `docker compose logs cube`
the rollup tables are `dev_pre_aggregations_250m.*`. A value of `DATASET` other than letters and digits makes the auth and actions
services refuse to start (it ends up in a schema name).

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
- **The Dataset switch** (live / 250M benchmark in the header, two Cubes) is a local feature and is not offered on a public host: the
  benchmark Cube from `run_scale.sh` is published on the server's localhost only. On a public host use `DATASET` above instead.
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

## Dashboards from YAML (`/d/`)
`dashboard-cube` also serves the dashboard renderer: `/d/` lists the dashboards the signed-in role may open and `/d/<id>` draws one
(specs in `dashboards/*.yml`, compiled to the committed `dashboards/build/`; see `dashboards/README.md`). The first deploy of this needs the
service recreated, because it gets a new mount and nginx routes: `git pull && docker compose up -d dashboard-cube`. After that a new or
changed dashboard is only `git pull` (nginx reads the JSON on each request). Nothing else changes: the sales dashboard stays at `/`.
