-- One row, rewritten by every successful build. Cube's pre-aggregation refresh_key reads it
-- (SELECT built_at FROM mart.data_version), so rollups rebuild when the mart changed and not on a
-- clock: a 5-minute pipeline cycle becomes visible in the dashboard within about a minute of
-- the cycle ending, without rebuilding anything in between.
select cast(now() as datetime) as built_at
