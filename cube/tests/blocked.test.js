// Datasets: a cube the token lists in blocked_cubes is refused by queryRewrite, whatever the role: `node cube/tests/blocked.test.js` (no Cube or database needed).
const assert = require('assert');

process.env.CUBEJS_API_SECRET = 'x';
const { queryRewrite } = require('../cube.js');

const ask = (sc, query) => { try { return { ok: queryRewrite(query, { securityContext: sc }) }; } catch (e) { return { error: e }; } };
const sales = { measures: ['internet_sales.revenue'], dimensions: ['products.category'] };
const base = { user_id: 'u', role: 'editor', territories: ['Canada'] };

assert(ask(base, sales).ok, 'no blocked_cubes claim: nothing is blocked (an older token)');
assert(ask({ ...base, blocked_cubes: [] }, sales).ok, 'an empty list blocks nothing');
for (const [cube, q] of [['internet_sales', sales], ['products', sales], ['dates', { measures: ['internet_sales.revenue'], timeDimensions: [{ dimension: 'dates.full_date' }] }],
  ['territories', { ...sales, filters: [{ member: 'territories.region', operator: 'equals', values: ['Canada'] }] }]]) {
  const r = ask({ ...base, blocked_cubes: [cube] }, q);
  assert(r.error, `${cube} is refused when blocked`);
  assert(/dataset/.test(String(r.error.message || r.error)), 'and the message says why');
}
assert(ask({ ...base, blocked_cubes: ['reseller_sales'] }, sales).ok, 'a blocked cube the query does not touch changes nothing');
assert(ask({ user_id: 'a', role: 'admin', blocked_cubes: [] }, sales).ok, 'an admin is blocked from nothing (the auth service sends an empty list for admins)');
console.log('blocked cubes: ok');

// single fields a dataset holds
{
  const sc = { ...base, blocked_members: ['internet_sales.gross_profit'] };
  assert(ask(sc, { measures: ['internet_sales.revenue'] }).ok, 'the rest of the cube is open');
  const r = ask(sc, { measures: ['internet_sales.gross_profit'] });
  assert(r.error && /dataset/.test(r.error.message), 'a blocked field is refused');
  assert(ask(sc, { measures: ['internet_sales.revenue'], order: { 'internet_sales.gross_profit': 'desc' } }).error, 'also when only ordered by');
  assert(ask(sc, { measures: ['internet_sales.revenue'], filters: [{ member: 'internet_sales.gross_profit', operator: 'gt', values: ['1'] }] }).error, 'or filtered on');
  assert(ask({ user_id: 'a', role: 'admin', blocked_members: [] }, { measures: ['internet_sales.gross_profit'] }).ok, 'admins are blocked from nothing');
  console.log('blocked fields: ok');
}
