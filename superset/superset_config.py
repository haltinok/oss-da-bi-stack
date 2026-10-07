import os

# No weak fallbacks: docker-compose passes both from .env. Failing loudly here is
# better than starting with a guessable secret or the wrong database.
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# Superset's own metadata store (dashboards, charts, users, saved queries).
# Stored in the shared Postgres container (database `superset_meta`, created by
# postgres/init/01_init.sql). Requires the psycopg2 driver, which is installed
# in the Superset image build (superset/Dockerfile).
LANGUAGES = {
    "en": {"flag": "us", "name": "English"},
    "tr": {"flag": "tr", "name": "Turkçe"},
}
# Default UI language; users can switch in the UI. Set SUPERSET_DEFAULT_LOCALE
# in .env (`en` or `tr`).
BABEL_DEFAULT_LOCALE = os.environ.get("SUPERSET_DEFAULT_LOCALE", "en")

# Metadata connection comes from the environment so no credentials live in git.
SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_METADATA_DB_URI"]

# Built-in MCP server (superset mcp run). Development mode: no auth, all
# operations run as this user. Never use this outside local dev.
MCP_DEV_USERNAME = os.environ.get("MCP_DEV_USERNAME", "admin")

# Advertise all tools upfront instead of the search_tools meta-interface, so
# plain OpenAI-style function-calling clients get the full catalog directly.
MCP_TOOL_SEARCH_CONFIG = {"enabled": False}
