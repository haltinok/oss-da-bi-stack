// Datasets: a cube the token lists in blocked_cubes is refused by queryRewrite, whatever the role: `node cube/tests/blocked.test.js` (no Cube or database needed).
const assert = require('assert');

process.env.CUBEJS_API_SECRET = 'x';
const { queryRewrite } = require('../cube.js');

const ask = (sc, query) => { try { return { ok: queryRewrite(query, { securityContext: sc }) }; } catch (e) { return { error: e }; } };
const sales = { measures: ['internet_sales.revenue'], dimensions: ['products.category'] };
const base = { user_id: 'u', role: 'manager', territories: ['Canada'] };

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
