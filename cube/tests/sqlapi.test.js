// The SQL API sends members as objects when a statement uses an expression (COUNT(*), a dimension of a joined cube). queryRewrite turns them back into member names, so the role
// rules, row-level security and blocked cubes apply as to a named member; any other expression is refused for everyone but an admin: `node cube/tests/sqlapi.test.js`.
const assert = require('assert');

process.env.CUBEJS_API_SECRET = 'x';
const { queryRewrite } = require('../cube.js');

const ask = (sc, query) => { try { return { ok: queryRewrite(query, { securityContext: sc }) }; } catch (e) { return { error: e }; } };
const adhoc = (cube, sql, touched = [cube]) => ({ cubeName: cube, name: 'x', expression: [...touched, `return \`${sql}\``] });
const manager = { user_id: 'm', role: 'manager', territories: ['Canada'] };
const rep = { user_id: 'r', role: 'rep', territories: ['Germany'] };

// COUNT(*) is a measure by another name: the cube rules still apply to the cube it counts
let r = ask(manager, { measures: [adhoc('internet_sales', 'COUNT(*)')] });
assert(r.ok, 'a manager may COUNT(*) over a sales cube');
assert(r.ok.filters.some((f) => f.member === 'territories.region'), 'and is still limited to their territories');
r = ask(manager, { measures: [adhoc('inventory_health', 'COUNT(*)')] });
assert(r.error && /Inventory/.test(r.error.message), 'a manager may not COUNT(*) inventory');
assert(ask(manager, { measures: [adhoc('customers', 'COUNT(*)')] }).error, 'nor customers (admin only)');

// a dimension of a joined cube, and COUNT(DISTINCT dimension)
assert(ask(manager, { measures: [adhoc('internet_sales', 'COUNT(*)', ['internet_sales', 'products'])], dimensions: [adhoc('products', '${products.category}', ['products'])] }).ok, 'category by count over a join');
assert(ask(manager, { measures: [adhoc('internet_sales', 'COUNT(DISTINCT ${internet_sales.order_number})')] }).ok, 'COUNT(DISTINCT dimension)');

// the member names inside an expression are checked like named members
r = ask(rep, { measures: [adhoc('internet_sales', 'COUNT(DISTINCT ${internet_sales.gross_profit})')] });
assert(r.error && /Profit/.test(r.error.message), 'a rep cannot reach profit through COUNT(DISTINCT ...)');
r = ask(rep, { dimensions: [adhoc('internet_sales', '${internet_sales.product_cost}')] });
assert(r.error && /Profit/.test(r.error.message), 'nor through a plain member reference');
const marketing = { user_id: 'k', role: 'marketing' };
assert(ask(marketing, { dimensions: [adhoc('inventory_health', '${inventory_health.vendor_name}')] }).error, 'marketing cannot reach supplier data through an expression');
assert(ask(marketing, { measures: [adhoc('inventory_health', 'COUNT(*)')] }).ok, 'but may count inventory rows');

// anything else is refused: the rules cannot see inside it
for (const sql of ['SUM(${internet_sales.order_quantity})', 'UPPER(${products.category})', '(SELECT 1)', 'COUNT(*) + 1', '${internet_sales.gross_profit} * 2']) {
  const e = ask(manager, { measures: [adhoc('internet_sales', sql)] }).error;
  assert(e && /not available/.test(e.message), `refused for a manager: ${sql}`);
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
