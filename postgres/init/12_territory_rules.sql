-- The dbt seed (rls.user_regions in StarRocks) no longer decides anyone's territories: the territory dimension is a registry list and a person's territories are their rules.
-- This moves what the demo's seed said into rules, once (a marker in access.meta), and turns an existing database's territory dimension into a list:
--   na_manager sees the six North American territories, de_rep sees Germany (admin is not row-limited).
-- A person who already has a territory rule (for them, or for the group they are in: Managers for na_manager, Reps for de_rep) keeps exactly that: a new rule would widen it.
-- Your own users: see "Moving the dbt seed into rules" in docs/admin.md.
CREATE TABLE IF NOT EXISTS access.meta (key text PRIMARY KEY, value text NOT NULL, set_at timestamptz NOT NULL DEFAULT now());

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM access.meta WHERE key = 'territory_rules_from_seed') THEN
        RETURN;
    END IF;
    INSERT INTO access.rls_rule (principal_type, principal, dimension, "values", updated_by)
    SELECT 'user', 'na_manager', 'territory', ARRAY['Canada', 'Central', 'Northeast', 'Northwest', 'Southeast', 'Southwest'], 'defaults'
    WHERE NOT EXISTS (SELECT 1 FROM access.rls_rule WHERE dimension = 'territory'
                      AND ((principal_type = 'user' AND principal = 'na_manager') OR (principal_type = 'group' AND principal = 'Managers')))
    ON CONFLICT DO NOTHING;
    INSERT INTO access.rls_rule (principal_type, principal, dimension, "values", updated_by)
    SELECT 'user', 'de_rep', 'territory', ARRAY['Germany'], 'defaults'
    WHERE NOT EXISTS (SELECT 1 FROM access.rls_rule WHERE dimension = 'territory'
                      AND ((principal_type = 'user' AND principal = 'de_rep') OR (principal_type = 'group' AND principal = 'Reps')))
    ON CONFLICT DO NOTHING;
    -- an existing database keeps the territory row it was seeded with (10 only inserts missing ids): make it a list, and drop the seed flag
    UPDATE access.rls_dimension
       SET seed = false, values_source = '{"kind": "list", "values": ["Australia", "Canada", "Central", "France", "Germany", "Northeast", "Northwest", "Southeast", "Southwest", "United Kingdom"]}'::jsonb,
           updated_by = 'defaults', updated_at = now()
     WHERE id = 'territory' AND (seed OR values_source->>'kind' = 'seed_regions');
    INSERT INTO access.meta (key, value) VALUES ('territory_rules_from_seed', 'territory-rules') ON CONFLICT DO NOTHING;
END $$;
