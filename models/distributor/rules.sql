-- The distributor's people (keycloak/realm-spike.json, sync-users.sh): a regional manager sees one region, a field representative sees the dealers of their own name.
-- Run after access.sql (postgres/init/13_model_access.sh). Idempotent.
INSERT INTO access.rls_rule (principal_type, principal, dimension, "values", updated_by) VALUES
    ('user', 'marmara_mudur',    'dealer_region', ARRAY['Marmara'],          'defaults'),
    ('user', 'marmara_temsilci', 'sales_rep',     ARRAY['marmara_temsilci'], 'defaults'),
    ('user', 'ege_temsilci',     'sales_rep',     ARRAY['ege_temsilci'],     'defaults')
ON CONFLICT DO NOTHING;
