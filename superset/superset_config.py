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
SQLALCHEMY_DATABASE_URI = "postgresql+psycopg2://postgres:postgres@postgres:5432/superset_meta"
