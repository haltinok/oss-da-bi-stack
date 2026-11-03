// The SQL API sends members as objects when a statement uses an expression (COUNT(*), a dimension of a joined cube). queryRewrite turns them back into member names, so the dataset
// rules, row-level security and blocked cubes apply as to a named member; any other expression is refused for everyone but an admin: `node cube/tests/sqlapi.test.js`.
const assert = require('assert');

process.env.CUBEJS_API_SECRET = 'x';
const { queryRewrite } = require('../cube.js');

const ask = (sc, query) => { try { return { ok: queryRewrite(query, { securityContext: sc }) }; } catch (e) { return { error: e }; } };
const adhoc = (cube, sql, touched = [cube]) => ({ cubeName: cube, name: 'x', expression: [...touched, `return \`${sql}\``] });
const manager = { user_id: 'm', role: 'editor', territories: ['Canada'] };
const rep = { ...manager, user_id: 'r', territories: ['Germany'], blocked_members: ['internet_sales.gross_profit', 'internet_sales.product_cost'] };

// COUNT(*) is a measure by another name: the cube rules still apply to the cube it counts
let r = ask(manager, { measures: [adhoc('internet_sales', 'COUNT(*)')] });
assert(r.ok, 'an editor may COUNT(*) over a sales cube');
assert(r.ok.filters.some((f) => f.member === 'territories.region'), 'and is still limited to their territories');
r = ask({ ...manager, blocked_cubes: ['inventory_health'] }, { measures: [adhoc('inventory_health', 'COUNT(*)')] });
assert(r.error && /dataset/.test(r.error.message), 'a blocked cube cannot be counted');
assert(ask({ ...manager, blocked_cubes: ['customers'] }, { measures: [adhoc('customers', 'COUNT(*)')] }).error, 'nor customers');

// a dimension of a joined cube, and COUNT(DISTINCT dimension)
assert(ask(manager, { measures: [adhoc('internet_sales', 'COUNT(*)', ['internet_sales', 'products'])], dimensions: [adhoc('products', '${products.category}', ['products'])] }).ok, 'category by count over a join');
assert(ask(manager, { measures: [adhoc('internet_sales', 'COUNT(DISTINCT ${internet_sales.order_number})')] }).ok, 'COUNT(DISTINCT dimension)');

// the member names inside an expression are checked like named members
r = ask(rep, { measures: [adhoc('internet_sales', 'COUNT(DISTINCT ${internet_sales.gross_profit})')] });
assert(r.error && /dataset/.test(r.error.message), 'a person without profit cannot reach it through COUNT(DISTINCT ...)');
r = ask(rep, { dimensions: [adhoc('internet_sales', '${internet_sales.product_cost}')] });
assert(r.error && /dataset/.test(r.error.message), 'nor through a plain member reference');
const noSupplier = { user_id: 'k', role: 'editor', territories: ['Canada'], blocked_members: ['inventory_health.vendor_name'] };
assert(ask(noSupplier, { dimensions: [adhoc('inventory_health', '${inventory_health.vendor_name}')] }).error, 'supplier data is unreachable through an expression too');
assert(ask(noSupplier, { measures: [adhoc('inventory_health', 'COUNT(*)')] }).ok, 'but inventory rows may be counted');

// anything else is refused: the rules cannot see inside it
for (const sql of ['SUM(${internet_sales.order_quantity})', 'UPPER(${products.category})', '(SELECT 1)', 'COUNT(*) + 1', '${internet_sales.gross_profit} * 2']) {
  const e = ask(manager, { measures: [adhoc('internet_sales', sql)] }).error;
  assert(e && /not available/.test(e.message), `refused for an editor: ${sql}`);
}
assert(ask({ user_id: 'a', role: 'admin' }, { measures: [adhoc('internet_sales', 'SUM(${internet_sales.order_quantity})')] }).ok, 'an admin may use any expression');

// datasets: the cubes an expression touches count
const blocked = { ...manager, blocked_cubes: ['products'] };
r = ask(blocked, { dimensions: [adhoc('products', '${products.category}', ['products'])] });
assert(r.error && /dataset/.test(r.error.message), 'a blocked cube is refused through a joined dimension');
assert(ask(blocked, { measures: [adhoc('internet_sales', 'COUNT(*)', ['internet_sales', 'products'])] }).error, 'and through the cubes a COUNT(*) joins');

// not an expression we know: refused, never a crash
for (const bad of [{}, { cubeName: 'internet_sales' }, { expression: [] }, 42, { expression: 'x' }]) {
  const e = ask(manager, { measures: [bad] }).error;
  assert(e && /not available/.test(e.message), `a malformed member is refused cleanly: ${JSON.stringify(bad)}`);
}
console.log('sql api members: ok');

// a viewer is scoped like anyone else: by datasets and territory, and without territories sees no sales data
{
  const viewer = { user_id: 'v', role: 'viewer', territories: ['Canada'], blocked_members: ['internet_sales.gross_profit'] };
  assert(ask(viewer, { measures: ['internet_sales.revenue'] }).ok, 'a viewer may read revenue');
  assert(ask(viewer, { measures: ['internet_sales.gross_profit'] }).error, 'but not a field no dataset gives them');
  assert(ask({ user_id: 'v', role: 'viewer' }, { measures: ['internet_sales.revenue'] }).error, 'and a viewer without territories sees no sales data');
}
console.log('viewer: ok');
