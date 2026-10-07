FROM apache/superset:6.1.0

# Database drivers so Superset can connect to the analytics warehouse and
# the ClickHouse CDC landing zone. The base image ships only with SQLite; its
# Python env is a uv-managed venv (/app/.venv) with no pip, so use `uv pip install`
# against that venv. `bin/python`, not `bin/python3.X`, so a base-image bump
# that changes the Python minor version does not break the build.
#
# Pinned to the versions Superset 6.1.0's own extras resolve to
# (`apache-superset[postgres,clickhouse,fastmcp]==6.1.0`); re-resolve them when
# the base image is bumped.
USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache \
        psycopg2-binary==2.9.9 \
        clickhouse-connect==0.15.1 \
        fastmcp==3.4.8

# The base image ships translation *source* (.po) files but not the compiled
# messages.json language packs, so /superset/language_pack/<lang>/ returns 404
# for every locale. Compile them at build time.
COPY compile_translations.py /app/compile_translations.py
RUN /app/.venv/bin/python /app/compile_translations.py

USER superset
