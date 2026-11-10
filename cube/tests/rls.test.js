// Row-level dimensions (rls_registry.js; without CUBE_ACCESS_PG_PASSWORD the default file rls_dimensions.json): `node cube/tests/rls.test.js` (no Cube or database needed).
const assert = require('assert');

process.env.CUBEJS_API_SECRET = 'x';
const { queryRewrite } = require('../cube.js');
const registry = require('../rls_registry.js');
const dims = registry.state.dimensions;                                      // what queryRewrite enforces (read at query time)

const ask = (sc, query) => { try { return { ok: queryRewrite(query, { securityContext: sc }) }; } catch (e) { return { error: e }; } };
const base = { user_id: 'u', role: 'editor' };
const bikes = { product_category: ['Bikes'] };                                 // the second real dimension, so the sales cubes are open for these people
const mk = () => ({ measures: ['internet_sales.revenue'], dimensions: ['products.category'] });       // queryRewrite adds filters to the query it is given
const filterOn = (r, member) => (r.ok.filters || []).filter((f) => f.member === member);

// territory, from the rls claim (the old `territories` claim is gone: a token that only has it has no territory)
let r = ask({ ...base, rls: { territory: ['Canada', 'Germany'], ...bikes } }, mk());
assert.deepStrictEqual(filterOn(r, 'territories.region')[0].values, ['Canada', 'Germany'], 'the rls claim limits the territories');
r = ask({ ...base, territories: ['Canada'], rls: bikes }, mk());
assert(r.error && /No territories assigned/.test(r.error.message), 'an older token with only `territories` is not rescued by it: no territory, no sales data');
r = ask({ ...base, rls: { territory: [], ...bikes }, territories: ['Canada'] }, mk());
assert(r.error && /No territories assigned/.test(r.error.message), 'an empty rls list is not rescued by the older claim either');
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

// the token must come from the same registry: a version that differs is refused, none at all (an older auth service) is let through, an admin is not checked
r = ask({ ...base, rls: { territory: ['Canada'], ...bikes }, rls_version: registry.state.version }, mk());
assert(r.ok, 'a token from this registry is served');
r = ask({ ...base, rls: { territory: ['Canada'], ...bikes }, rls_version: '0000000000000000' }, mk());
assert(r.error && r.error.status === 403 && /dimensions changed/.test(r.error.message), 'a token from another registry is refused');
assert(ask({ user_id: 'a', role: 'admin', rls_version: 'x' }, mk()).ok, 'an admin is not limited by rows, so not by the version either');
assert.strictEqual(registry.state.source, 'file', 'without CUBE_ACCESS_PG_PASSWORD the default file is the registry');
assert(/^[0-9a-f]{16}$/.test(registry.state.version), 'the version is a short hash');

// validation: anything Cube could not enforce exactly is refused (Cube then does not start)
const file = require('../rls_dimensions.json').dimensions;
const bad = (mutate, re, why) => {
  const copy = JSON.parse(JSON.stringify(file));
  mutate(copy);
  assert.throws(() => registry.normalize(copy), (e) => e.name === 'RegistryError' && re.test(e.message), why);
};
assert.throws(() => registry.normalize([]), /no dimensions/, 'an empty registry would leave every row open');
bad((d) => { d[0].when_empty = 'maybe'; }, /when_empty/, 'an unknown when_empty');
bad((d) => { d[0].member = 'region'; }, /cube\.field/, 'a member that is not cube.field');
bad((d) => { d[0].cubes = []; }, /cubes/, 'no cubes');
bad((d) => { d[1].id = d[0].id; }, /used twice/, 'two dimensions with one id');
bad((d) => { d[1].values = { kind: 'list', values: [] }; }, /values list/, 'an empty values list');
bad((d) => { d[0].values = { kind: 'sql' }; }, /values.kind/, 'an unknown kind of values');
bad((d) => { d[0].seed = 'yes'; }, /seed/, 'seed that is not a boolean');
assert.deepStrictEqual(registry.normalize([{ id: 'x', member: 'a.b', cubes: ['a'], when_empty: 'allow' }]),
  [{ id: 'x', member: 'a.b', cubes: ['a'], when_empty: 'allow', values: { kind: 'cube' }, seed: false, labels: {}, empty_message: '' }], 'missing fields get their defaults');
assert.strictEqual(registry.version(registry.normalize(file)), registry.state.version, 'the version depends on the content only');

// a database row (what rls_registry_load.js prints) becomes the same entry as the file's
const row = { id: 'territory', member: 'territories.region', cubes: ['internet_sales'], when_empty: 'deny', values_source: { kind: 'seed_regions' }, seed: true, labels: { en: 'T' }, empty_message: 'none' };
assert.deepStrictEqual(registry.normalize([registry.fromRow(row)])[0], { id: 'territory', member: 'territories.region', cubes: ['internet_sales'], when_empty: 'deny', values: { kind: 'seed_regions' }, seed: true, labels: { en: 'T' }, empty_message: 'none' });

// with a password but no database, loading fails (and so does Cube's start), it never falls back to the file
assert.throws(() => registry.load({ ...process.env, CUBE_ACCESS_PG_PASSWORD: 'pw', CUBE_ACCESS_PG_HOST: '127.0.0.1', CUBE_ACCESS_PG_PORT: '1', RLS_REGISTRY_WAIT: '0' }),
  /cannot read the row-level dimensions/, 'an unreadable database stops Cube instead of using the file');
console.log('row-level dimensions: ok');
