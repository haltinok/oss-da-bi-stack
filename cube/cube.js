// StarRocks speaks the MySQL protocol, so Cube uses its MySQL dialect, with one change
// (see StarRocksQuery), plus the security layer: checkAuth + queryRewrite.
const jwt = require('jsonwebtoken');
const { CubejsHandlerError } = require('@cubejs-backend/api-gateway/dist/src/cubejs-handler-error');
const { MysqlQuery } = require('@cubejs-backend/schema-compiler/dist/src/adapter/MysqlQuery');

// --- Dialect ---------------------------------------------------------------
// The stock dialect wraps every time column in CONVERT_TZ(col, @@session.time_zone, ...).
// That hides the column from StarRocks' partition pruning: each monthly
// pre-aggregation partition then scanned all 122 fact partitions instead of one
// (measured with EXPLAIN: partitions=122/122 vs 1/122). The mart stores UTC
// datetimes and Cube runs in UTC, so the conversion is an identity; leave the
// column bare.
class StarRocksQuery extends MysqlQuery {
  convertTz(field) {
    return field;
  }

  timeStampCast(value) {
    return `CAST(${value} AS DATETIME)`;
  }
}

// --- Security --------------------------------------------------------------
// Tokens are minted by auth/ after Keycloak login: {user_id, role, territories, exp}.
// checkAuth verifies them itself (rather than relying on dev-mode defaults) so a missing,
// expired or tampered token is always rejected.
const SECRET = process.env.CUBEJS_API_SECRET;
const FACT_CUBES = new Set(['internet_sales', 'reseller_sales']);
const REFERENCE_CUBES = new Set(['products', 'dates']);       // no territory-scoped data
const PROFIT_MEMBERS = new Set(['gross_profit', 'margin_pct', 'product_cost']);
// Inventory data is not territory-bound, so it is gated by role instead: purchasing sees the reorder
// side, marketing sees stock and offers but nothing about suppliers or order sizes; managers and reps see neither.
const INVENTORY_CUBES = new Set(['inventory_health', 'offer_performance']);
const ROLE_CUBES = {
  purchasing: new Set(['inventory_health', 'products']),
  marketing: new Set(['inventory_health', 'offer_performance', 'products']),
};
const SUPPLIER_MEMBERS = new Set([
  'vendor_id', 'vendor_name', 'unit_cost', 'lead_time_days', 'replenishment_type',
  'suggested_order_qty', 'suggested_order_value', 'suggested_order_qty_total', 'suggested_order_value_total',
  'min_order_qty', 'max_order_qty',
]);

// Cube turns a thrown CubejsHandlerError into its HTTP status; any other error is a 500
// (with a stack trace in dev mode). Messages stay generic: they go back to the caller.
const unauthorized = () => new CubejsHandlerError(401, 'Unauthorized', 'Invalid or missing token');
const forbidden = (why) => new CubejsHandlerError(403, 'Forbidden', why);

function checkAuth(req, auth) {
  if (!auth) {
    throw unauthorized();
  }
  let claims;
  try {
    claims = jwt.verify(auth.replace(/^Bearer /i, ''), SECRET, { algorithms: ['HS256'] });
  } catch (e) {
    throw unauthorized();
  }
  if (!claims.user_id || !claims.role) {
    throw unauthorized();
  }
  req.securityContext = claims;
}

// Every member the query touches, including inside nested and/or filters.
function membersOf(query) {
  const out = [...(query.measures || []), ...(query.dimensions || [])];
  (query.timeDimensions || []).forEach((t) => out.push(t.dimension));
  (query.segments || []).forEach((s) => out.push(s));
  // order is {member: 'asc'} or [[member, 'asc'], ...]; ordering by a hidden measure leaks its ranking.
  const order = query.order || [];
  (Array.isArray(order) ? order.map((o) => o[0]) : Object.keys(order)).forEach((m) => out.push(m));
  const walk = (filters) => (filters || []).forEach((f) => {
    if (f.member) out.push(f.member);
    walk(f.and);
    walk(f.or);
  });
  walk(query.filters);
  return out;
}

function queryRewrite(query, { securityContext }) {
  const sc = securityContext || {};
  if (!sc.user_id || !sc.role) {
    throw unauthorized();
  }
  const members = membersOf(query);
  const cubes = new Set(members.map((m) => m.split('.')[0]));

  // Cost/profit are hidden from reps, whichever cube asks for them.
  if (sc.role === 'rep' && members.some((m) => PROFIT_MEMBERS.has(m.split('.')[1]))) {
    throw forbidden('Profit and margin are not available for your role');
  }
  if (sc.role === 'admin') {
    return query;
  }
  if (ROLE_CUBES[sc.role]) {
    if (![...cubes].every((c) => ROLE_CUBES[sc.role].has(c)) || ![...cubes].some((c) => INVENTORY_CUBES.has(c))) {
      throw forbidden('Not available for your role');
    }
    if (sc.role === 'marketing' && members.some((m) => m.startsWith('inventory_health.') && SUPPLIER_MEMBERS.has(m.split('.')[1]))) {
      throw forbidden('Supplier and order data are not available for your role');
    }
    return query;
  }
  if ([...cubes].some((c) => INVENTORY_CUBES.has(c))) {
    throw forbidden('Inventory data is not available for your role');
  }

  const territories = Array.isArray(sc.territories) ? sc.territories : [];
  if (territories.length === 0) {
    throw forbidden('No territories assigned');
  }
  // Customer-level data (PII) is admin-only.
  if (cubes.has('customers')) {
    throw forbidden('Customer data is not available for your role');
  }
  const touchesSales = [...cubes].some((c) => FACT_CUBES.has(c));
  const onlyReference = [...cubes].every((c) => REFERENCE_CUBES.has(c));
  if (!touchesSales && !cubes.has('territories') && !onlyReference) {
    throw forbidden('Not available for your role');
  }
  if (touchesSales || cubes.has('territories')) {
    // ANDed with whatever the client asked for, so asking for another region yields nothing.
    query.filters = [...(query.filters || []),
      { member: 'territories.region', operator: 'equals', values: territories }];
  }
  return query;
}

module.exports = {
  dialectFactory: () => StarRocksQuery,
  checkAuth,
  queryRewrite,
};
