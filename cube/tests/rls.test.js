// Row-level dimensions (cube/rls_dimensions.json): `node cube/tests/rls.test.js` (no Cube or database needed).
const assert = require('assert');

process.env.CUBEJS_API_SECRET = 'x';
const { queryRewrite } = require('../cube.js');
const dims = require('../rls_dimensions.json').dimensions;

const ask = (sc, query) => { try { return { ok: queryRewrite(query, { securityContext: sc }) }; } catch (e) { return { error: e }; } };
const base = { user_id: 'u', role: 'editor' };
const bikes = { product_category: ['Bikes'] };                                 // the second real dimension, so the sales cubes are open for these people
const mk = () => ({ measures: ['internet_sales.revenue'], dimensions: ['products.category'] });       // queryRewrite adds filters to the query it is given
const filterOn = (r, member) => (r.ok.filters || []).filter((f) => f.member === member);

// territory, from the rls claim and from an older token that only has `territories`
let r = ask({ ...base, rls: { territory: ['Canada', 'Germany'], ...bikes } }, mk());
assert.deepStrictEqual(filterOn(r, 'territories.region')[0].values, ['Canada', 'Germany'], 'the rls claim limits the territories');
r = ask({ ...base, territories: ['Canada'], rls: bikes }, mk());
assert.deepStrictEqual(filterOn(r, 'territories.region')[0].values, ['Canada'], 'an older token with only territories still works');
r = ask({ ...base, rls: { territory: [], ...bikes }, territories: ['Canada'] }, mk());
assert(r.error && /No territories assigned/.test(r.error.message), 'an empty rls list is not rescued by the older claim');
assert(ask({ ...base, rls: bikes }, mk()).error, 'no territory: denied (when_empty deny)');
assert(ask({ ...base, rls: { territory: ['Canada'] } }, { measures: ['inventory_health.stockout_items'] }).ok, 'cubes outside every dimension are not filtered');
assert(!ask({ ...base, rls: { territory: ['Canada'] } }, { measures: ['inventory_health.stockout_items'] }).ok.filters, 'and get no filter');
assert(ask({ user_id: 'a', role: 'admin' }, mk()).ok, 'an admin is not limited');

// product categories: a person with territories but no category sees no sales; one category limits the rows (ANDed with the territory)
r = ask({ ...base, rls: { territory: ['Canada'] } }, mk());
assert(r.error && /No product categories assigned/.test(r.error.message), 'no category value: no sales data');
r = ask({ ...base, rls: { territory: ['Canada'], product_category: ['Bikes', 'Clothing'] } }, mk());
assert.deepStrictEqual(filterOn(r, 'products.category')[0].values, ['Bikes', 'Clothing'], 'the categories limit the rows');
assert(ask({ ...base, rls: { territory: ['Canada'] } }, { measures: ['inventory_health.stockout_items'], dimensions: ['products.category'] }).ok, 'inventory by category is not a sales query, so it needs no category rule');

// a made-up third dimension: ANDed with territory and category, denied or allowed when empty
const extra = { id: 'fake', member: 'products.subcategory', cubes: ['internet_sales'], when_empty: 'deny', empty_message: 'No fakes assigned' };
dims.push(extra);
r = ask({ ...base, rls: { territory: ['Canada'], ...bikes, fake: ['Mountain Bikes'] } }, mk());
assert(filterOn(r, 'territories.region').length === 1 && filterOn(r, 'products.subcategory')[0].values[0] === 'Mountain Bikes' && filterOn(r, 'products.category')[0].values[0] === 'Bikes', 'two dimensions: both filters are added (AND)');
r = ask({ ...base, rls: { territory: ['Canada'], ...bikes } }, mk());
assert(r.error && /No fakes assigned/.test(r.error.message), 'deny: a person with no value for it gets nothing from the cubes of that dimension');
extra.when_empty = 'allow';
r = ask({ ...base, rls: { territory: ['Canada'], ...bikes } }, mk());
assert(r.ok && filterOn(r, 'products.subcategory').length === 0, 'allow: no value means no restriction');
dims.pop();
console.log('row-level dimensions: ok');
