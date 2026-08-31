FROM apache/superset:latest

# Database drivers so Superset can connect to the analytics warehouse and
# the ClickHouse CDC landing zone. The base image ships only with SQLite; its
# Python env is a uv-managed venv (/app/.venv) with no pip, so use `uv pip install`
# against that venv.
USER root
RUN uv pip install --python /app/.venv/bin/python3.10 --no-cache psycopg2-binary clickhouse-connect

# The base image ships translation *source* (.po) files but not the compiled
# messages.json language packs, so /superset/language_pack/<lang>/ returns 404
# for every locale. Compile them at build time.
COPY compile_translations.py /app/compile_translations.py
RUN /app/.venv/bin/python3.10 /app/compile_translations.py

USER superset
