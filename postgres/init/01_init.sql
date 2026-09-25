-- Airflow's own metadata database
CREATE DATABASE airflow;

-- Superset's own metadata database (dashboards, charts, users — not the data it visualizes)
CREATE DATABASE superset_meta;

-- Metabase's own metadata database (questions, dashboards, users)
CREATE DATABASE metabase_meta;

-- The actual analytics warehouse dlt/dbt operate on, and what Superset visualizes
CREATE DATABASE analytics;

\connect analytics

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stage;
-- dbt writes the marts here (models/marts -> +schema: mart)
CREATE SCHEMA IF NOT EXISTS mart;
