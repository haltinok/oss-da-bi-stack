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
  * dbt (`profiles.yml`), Superset (`superset_config.py`) and the dlt
    pipelines read their credentials from the environment.
  * The Debezium connector config references `${env:DEBEZIUM_PASSWORD}`, which
    Kafka Connect resolves at runtime, so the password is not stored in
    Connect's config topic or returned by its REST API.
  * ClickHouse creates its user from `CLICKHOUSE_PASSWORD`; there is no
    committed `users.xml`.
  * The Superset dashboard export carries a masked password, restored from
    `BI_READONLY_PASSWORD` by `superset/set_bi_database.py`.
* **Only the optional SQL Server load needs a secrets file:**
  `dlt/pipelines/sqlserver_to_postgres/.dlt/secrets.toml`, created from
  `secrets.toml.example` and git-ignored.
* **Least privilege for BI.** Superset, Metabase and the ClickHouse mart sync
  read the warehouse as the `bi_ro` role, which can only `SELECT` from `mart`.
* **Local-only ports.** Every published port binds to `127.0.0.1`. Several
  services are unauthenticated by design (Superset MCP server, Kafka UI, Kafka
  Connect REST); never publish them on a public interface.

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
