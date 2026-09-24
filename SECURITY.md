# Security notes

## Credentials that were committed to this (public) repository

`https://github.com/haltinok/oss-da-bi-stack` is **public**, and the following
files were tracked in git. Anyone who cloned or browsed the repo has them.

| File | What was exposed |
|------|------------------|
| `dlt/pipelines/sqlserver_to_postgres/.dlt/secrets.toml` | SQL Server login `ANALYZER` + password, host `192.168.1.148` (a later working-tree revision pointed at `192.168.1.181`), port `1433` |
| `dlt/pipelines/postgres_active_to_postgres/.dlt/secrets.toml` | warehouse + source Postgres passwords |
| `dbt/adventureworks_dwh/profiles.yml` | warehouse Postgres user/password |
| `superset/superset_config.py` | Superset metadata Postgres URI (inline) |

The last three are only the local demo's `postgres`/`postgres`, which is not a
meaningful secret. **The SQL Server credential is a real one and must be treated
as compromised.**

## Immediate actions (do these first)

1. **Rotate the SQL Server `ANALYZER` password.** Assume it is public. While you
   are there, check what that login can reach and whether it needs to be
   reachable from outside `192.168.1.0/24`.
2. Rotate the Postgres passwords if this stack is ever exposed beyond localhost
   (`postgres` on the warehouse and on `postgres_active`, plus the `debezium`
   replication user).
3. Rotate `SUPERSET_SECRET_KEY` / `AIRFLOW_FERNET_KEY` / `AIRFLOW_WEBSERVER_SECRET_KEY`
   if they were ever set to real values rather than the `changeme` placeholders.

## Already fixed in the working tree

* `dlt/**/.dlt/secrets.toml` — untracked, plus `secrets.toml.example` templates
  and a `.gitignore` rule (`**/.dlt/secrets.toml`).
* `dbt/adventureworks_dwh/profiles.yml` — now reads `DBT_PG_*` / `POSTGRES_PASSWORD`
  from the environment.
* `superset/superset_config.py` — now reads `SUPERSET_METADATA_DB_URI` /
  `SUPERSET_WAREHOUSE_DB_URI` from the environment.
* Build artifacts and logs — 155 dbt files (`target/`, `logs/`) and 14
  `airflow/logs/*` files are untracked and git-ignored.

Untracking is **not** enough on its own: the blobs are still in history. The
steps below are required to actually remove them.

## Purging git history

Run this on a **fresh clone** (nothing else in flight). `git filter-repo` is
preferred; BFG works too.

```bash
pipx install git-filter-repo
git clone https://github.com/haltinok/oss-da-bi-stack.git repo-clean && cd repo-clean

# 1. Drop the secret files and the build artifacts from every commit.
git filter-repo --force \
  --path dlt/pipelines/sqlserver_to_postgres/.dlt/secrets.toml \
  --path dlt/pipelines/postgres_active_to_postgres/.dlt/secrets.toml \
  --path dbt/adventureworks_dwh/target \
  --path dbt/adventureworks_dwh/logs \
  --path airflow/logs \
  --invert-paths

# 2. Scrub the private host addresses wherever else they appear in history.
git filter-repo --force \
  --replace-text <(printf '192.168.1.148==>REDACTED_HOST\n192.168.1.181==>REDACTED_HOST\n')

# 3. filter-repo removes the remote; put it back and force-push.
git remote add origin https://github.com/haltinok/oss-da-bi-stack.git
git push --force --all && git push --force --tags
```

Caveats worth knowing before you start:

* A force-push does **not** reach clones that already exist (including your own
  working copies — re-clone), forks, or GitHub's cached object views. For a
  credential leak, the only fully reliable fix is to **delete and recreate the
  repository**, or ask GitHub Support to expire the cached blobs.
* `git filter-repo` rewrites every commit hash, so open PRs and any local
  branches must be re-based or re-created.

## Preventing a repeat

* `pre-commit` with `gitleaks` / `detect-secrets`, or GitHub's native secret
  scanning + push protection.
* Keep the `secrets.toml.example` → `secrets.toml` (git-ignored) flow; never
  commit the filled-in file.
* The `.gitignore` in this repo now covers `.env*`, `**/.dlt/secrets.toml`,
  dbt `target/`+`logs/`, and `airflow/logs/`.
