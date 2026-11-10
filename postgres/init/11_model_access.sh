#!/bin/bash
# For a model that is not AdventureWorks (docker-compose.distributor.yml sets MODEL_ACCESS_SQL on a fresh database): 08, 09 and 10 seed the AdventureWorks datasets, grants, row
# rules and row-level dimensions; this runs the model's own seed (<model>/access.sql, which empties those first) so the services start with the model's.
set -euo pipefail
if [ -n "${MODEL_ACCESS_SQL:-}" ]; then
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$MODEL_ACCESS_SQL"
fi
