-- Starter row rules for the product-category dimension (cube/rls_dimensions.json: when_empty = deny). Without a category rule nobody but an admin would see the sales cubes,
-- so the two groups that had sales access get every category, once (a marker in access.meta; an admin who later changes or removes the rule is not overridden).
-- Anyone else who should see sales data (a viewer outside these groups, say) needs a rule: Row rules tab, Product categories.
CREATE TABLE IF NOT EXISTS access.meta (key text PRIMARY KEY, value text NOT NULL, set_at timestamptz NOT NULL DEFAULT now());

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM access.meta WHERE key = 'rls_category_defaults') THEN
        RETURN;
    END IF;
    INSERT INTO access.rls_rule (principal_type, principal, dimension, "values", updated_by) VALUES
        ('group', 'Managers', 'product_category', ARRAY['Accessories', 'Bikes', 'Clothing', 'Components', 'Uncategorized'], 'defaults'),
        ('group', 'Reps',     'product_category', ARRAY['Accessories', 'Bikes', 'Clothing', 'Components', 'Uncategorized'], 'defaults')
    ON CONFLICT DO NOTHING;
    INSERT INTO access.meta (key, value) VALUES ('rls_category_defaults', 'product-category') ON CONFLICT DO NOTHING;
END $$;
