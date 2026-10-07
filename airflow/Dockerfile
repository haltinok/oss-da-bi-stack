FROM apache/airflow:3.3.2-python3.11

USER root
# No compiler toolchain: every package in requirements.txt installs from a
# prebuilt wheel (dbt 1.11 dropped logbook, the last one that needed a build).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libpq-dev curl gnupg \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
