-- The starter datasets and grants that give the groups the data access the old data roles had (PLAN: roles say what a person may DO; data access is datasets, grants and row rules).
-- Seeded once (a marker in access.meta), so a dataset an admin later changes or deletes is not put back. The groups are Keycloak groups (keycloak/realm-spike.json, keycloak/sync-users.sh).
CREATE TABLE IF NOT EXISTS access.meta (key text PRIMARY KEY, value text NOT NULL, set_at timestamptz NOT NULL DEFAULT now());

DO $$
DECLARE
    supplier text[] := ARRAY['inventory_health.vendor_id', 'inventory_health.vendor_name', 'inventory_health.unit_cost', 'inventory_health.lead_time_days', 'inventory_health.replenishment_type',
                             'inventory_health.suggested_order_qty', 'inventory_health.suggested_order_value', 'inventory_health.suggested_order_qty_total',
                             'inventory_health.suggested_order_value_total', 'inventory_health.min_order_qty', 'inventory_health.max_order_qty'];
    profit text[] := ARRAY['internet_sales.gross_profit', 'internet_sales.margin_pct', 'internet_sales.product_cost', 'reseller_sales.gross_profit', 'reseller_sales.margin_pct', 'reseller_sales.product_cost'];
BEGIN
    IF EXISTS (SELECT 1 FROM access.meta WHERE key = 'defaults_seeded') THEN
        RETURN;
    END IF;
    INSERT INTO access.dataset (id, name, description, cubes, members, updated_by) VALUES
        ('sales',     'Sales',            'The sales facts and their territories (limited to the person''s own territories).', ARRAY['internet_sales', 'reseller_sales', 'territories'], '{}', 'defaults'),
        ('profit',    'Profit and margin', 'Profit, margin and product cost of the sales facts.',                                  '{}', profit, 'defaults'),
        ('customers', 'Customers',        'Customer-level data (names, emails). No grants by default: admins only.',               ARRAY['customers'], '{}', 'defaults'),
        ('inventory', 'Inventory',        'Stock, reorder and overstock.',                                                         ARRAY['inventory_health'], '{}', 'defaults'),
        ('offers',    'Offers',           'How past special offers performed.',                                                    ARRAY['offer_performance'], '{}', 'defaults'),
        ('supplier',  'Supplier and order data', 'Vendors, unit costs, lead times and suggested order sizes.',                          '{}', supplier, 'defaults')
    ON CONFLICT (id) DO NOTHING;
    INSERT INTO access."grant" (object_type, object_id, principal_type, principal, permission, granted_by) VALUES
        ('dataset', 'sales',     'group', 'Managers',   'view', 'defaults'),
        ('dataset', 'sales',     'group', 'Reps',       'view', 'defaults'),
        ('dataset', 'sales',     'role',  'viewer',     'view', 'defaults'),
        ('dataset', 'profit',    'group', 'Managers',   'view', 'defaults'),
        ('dataset', 'inventory', 'group', 'Purchasing', 'view', 'defaults'),
        ('dataset', 'inventory', 'group', 'Marketing',  'view', 'defaults'),
        ('dataset', 'offers',    'group', 'Marketing',  'view', 'defaults'),
        ('dataset', 'supplier',  'group', 'Purchasing', 'view', 'defaults')
    ON CONFLICT DO NOTHING;
    INSERT INTO access.meta (key, value) VALUES ('defaults_seeded', 'roles-as-capabilities') ON CONFLICT DO NOTHING;
END $$;
