import os

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "changeme_superset_secret")

# Superset's own metadata store (dashboards, charts, users, saved queries).
# Stored in the shared Postgres container (database `superset_meta`, created by
# postgres/init/01_init.sql). Requires the psycopg2 driver, which is installed
# in the Superset image build (superset/Dockerfile).
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "tr": {"flag": "tr", "name": "Turkçe"},
}
BABEL_DEFAULT_LOCALE = "tr"

# Metadata connection comes from the environment so no credentials live in git.
# The default matches the local demo stack only.
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SUPERSET_METADATA_DB_URI",
    "postgresql+psycopg2://postgres:postgres@postgres:5432/superset_meta",
)

# Credentials used by charts to reach the warehouse. Same rationale as above;
# the `postgres`/`postgres` default matches the local demo stack only.
SUPERSET_WAREHOUSE_DB_URI = os.environ.get(
    "SUPERSET_WAREHOUSE_DB_URI",
    "postgresql+psycopg2://postgres:postgres@postgres:5432/analytics",
)

# Built-in MCP server (superset mcp run). Development mode: no auth, all
# operations run as this user. Never use this outside local dev.
MCP_DEV_USERNAME = os.environ.get("MCP_DEV_USERNAME", "admin")

# Advertise all tools upfront instead of the search_tools meta-interface, so
# plain OpenAI-style function-calling clients get the full catalog directly.
MCP_TOOL_SEARCH_CONFIG = {"enabled": False}
