-- Airflow's own metadata database
CREATE DATABASE airflow;

-- Small warehouse for the dlt loads (the optional SQL Server load and `orders`). The star schema
-- is built in StarRocks, not here.
CREATE DATABASE analytics;

\connect analytics

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stage;
-- dbt writes the marts here (models/marts -> +schema: mart)
CREATE SCHEMA IF NOT EXISTS mart;
