# Security

This is a local demo stack. It is built to run on one machine, not to be
exposed to a network. This page describes how it handles secrets and what
keeps them out of git.

## Reporting a problem

Please report a suspected leak or vulnerability privately through
**GitHub → Security → Report a vulnerability** on this repository, not in a
public issue.

## How secrets are handled

* **`.env` is the only place real secrets live.** It is git-ignored.
  `scripts/generate-env.sh` writes it with strong random values (mode `0600`).
  `.env.example` documents every variable and holds only placeholders.
* **No weak fallbacks.** `docker-compose.yml` requires each secret with
  Compose's `${VAR:?}` syntax, so the stack refuses to start rather than run
  with a guessable default.
* **Nothing sensitive in tracked files.**
  * dbt (`profiles.yml`), ingestr (via environment variables, so passwords never
    appear in a process list) and the dlt pipelines read their credentials from
    the environment.
  * The Debezium connector config references `${env:DEBEZIUM_PASSWORD}`, which
    Kafka Connect resolves at runtime, so the password is not stored in
    Connect's config topic or returned by its REST API.
  * ClickHouse creates its user from `CLICKHOUSE_PASSWORD`; there is no
    committed `users.xml`.
* **Only the optional SQL Server load needs a secrets file:**
  `dlt/pipelines/sqlserver_to_postgres/.dlt/secrets.toml`, created from
  `secrets.toml.example` and git-ignored.
* **Least privilege for reads.** Cube and the auth service read StarRocks as
  read-only users (`cube_ro`, `auth_ro`; see the `starrocks` profile below).
* **The `starrocks` profile** adds sign-in and row-level security, which the rest of the stack does not
  have: users log in through Keycloak, a small service (`auth/`) turns the login into a 15-minute
  Cube token carrying the user's territories, and Cube (`cube/cube.js`) adds the territory filter to
  every query and refuses profit/margin and customer data to roles that may not see them. Cube and the
  auth service read StarRocks as read-only users (`cube_ro`: the mart; `auth_ro`: only the `rls` schema).
  **Demo posture, not production:** Keycloak runs in `start-dev` (embedded H2, plain HTTP, direct password
  grants for the tests), the StarRocks `root` user has no password on the internal Docker network, and
  there is no audit log or TLS. A real deployment needs the organisation's identity provider, TLS,
  secrets management and a security review of `cube/cube.js` (see `spike/results.md`).
* **Local-only ports.** Every published port binds to `127.0.0.1`. Several
  services are unauthenticated by design (Kafka UI, Kafka
  Connect REST); never publish them on a public interface.
* **The one exception, on purpose: the public overlay** (`docker-compose.public.yml`, [`docs/deploy-demo.md`](docs/deploy-demo.md)).
  A Caddy container publishes 80 and 443 and nothing else does. It terminates TLS (Let's Encrypt) and forwards only
  `/kc/*` (Keycloak), `/auth-api/*`, `/actions-api/*`, `/cubejs-api/*` and the dashboard. Every one of those services
  checks the caller's token itself; Keycloak's admin console and master realm are answered with 404 at the proxy, and
  `keycloak/update-public-url.sh` switches off the dashboard client's direct password grant on a public host. Keycloak is still
  `start-dev` (embedded H2) and the stack runs simulated data under demo user passwords: **public does not mean production**, and
  no customer or bank data belongs on it.

## Guard rails

* **pre-commit** (`.pre-commit-config.yaml`): gitleaks, private-key detection
  and large-file checks. Run `pre-commit install` once after cloning.
* **CI** (`.github/workflows/ci.yml`): gitleaks over the full history on every
  push and pull request.
* **Dependabot** (`.github/dependabot.yml`): keeps the pinned GitHub Actions,
  Python requirements and Docker base images current.
* **Repository settings** to keep on: *Secret scanning*, *Push protection* and
  *Dependabot alerts* (Settings → Code security).

## If a secret is committed

1. **Rotate it first.** Assume anything pushed to a public repository has been
   copied; deleting the commit does not undo that.
2. Then remove it from history (`git filter-repo --invert-paths --path <file>`
   on a fresh mirror clone, then force-push), or recreate the repository from
   a clean tree.
3. Re-clone every working copy: old clones still hold the secret.
