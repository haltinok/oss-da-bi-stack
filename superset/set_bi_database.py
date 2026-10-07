"""Create/update the read-only BI database connection with the real password.

Superset masks passwords on export (the dashboard zip carries
``bi_ro:XXXXXXXXXX@...``), so importing it on a fresh instance would leave a broken
connection. This runs after ``superset import-dashboards`` and sets the real URI
from ``BI_READONLY_PASSWORD``.

Invoked by the ``superset-init`` service (docker-compose.yml).
"""

import os

NAME = "AdventureWorks mart (read-only)"


def main() -> None:
    # Import the app first: superset.models.core builds an encrypted column at
    # import time, which needs the app's encryption factory initialized.
    from superset.app import create_app

    app = create_app()
    with app.app_context():
        from superset import db
        from superset.models.core import Database

        uri = (
            "postgresql+psycopg2://bi_ro:"
            f"{os.environ['BI_READONLY_PASSWORD']}@postgres:5432/analytics"
        )
        database = db.session.query(Database).filter_by(database_name=NAME).one_or_none()
        if database is None:
            database = Database(database_name=NAME)
            db.session.add(database)
        database.set_sqlalchemy_uri(uri)
        db.session.commit()
        print(f"BI database '{NAME}' ready (id={database.id})")


if __name__ == "__main__":
    main()
