-- Hard-delete detection: merge loads never see deleted source rows, so each run
-- also snapshots the live primary keys (pk_* tables, full replace) and flags raw
-- rows whose key is gone. Phase 3 turns this into a dbt model that excludes them.
CREATE VIEW IF NOT EXISTS raw.recon_deleted_sales_order_header AS
SELECT h.sales_order_id
FROM raw.sales_order_header h
LEFT ANTI JOIN raw.pk_sales_order_header p ON p.sales_order_id = h.sales_order_id;

CREATE VIEW IF NOT EXISTS raw.recon_deleted_sales_order_detail AS
SELECT d.sales_order_id, d.sales_order_detail_id
FROM raw.sales_order_detail d
LEFT ANTI JOIN raw.pk_sales_order_header p ON p.sales_order_id = d.sales_order_id;
