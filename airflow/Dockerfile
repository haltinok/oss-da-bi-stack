FROM apache/airflow:3.3.2-python3.11

USER root
# No compiler toolchain: every package in requirements.txt installs from a
# prebuilt wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libpq-dev curl gnupg \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# ingestr: a single static binary (postgres_active -> StarRocks in the `starrocks` pipeline). Pinned;
# copied from the official image rather than downloaded, so the build needs no extra network access.
COPY --from=ghcr.io/bruin-data/ingestr:v1.1.73 --chmod=755 /usr/local/bin/ingestr /usr/local/bin/ingestr

USER airflow
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# dbt-starrocks in its own virtualenv, so its dbt-core pin and the packages above (Airflow, dlt)
# never have to agree.
COPY requirements-dbt-starrocks.txt /requirements-dbt-starrocks.txt
RUN python -m venv /home/airflow/dbt-starrocks \
    && /home/airflow/dbt-starrocks/bin/pip install --no-cache-dir -r /requirements-dbt-starrocks.txt
