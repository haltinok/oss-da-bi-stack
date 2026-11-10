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

  // The stock dialect truncates to a quarter with TIMESTAMPDIFF(QUARTER, ...), which StarRocks does not have ("No matching function with
  // signature: QUARTERS_diff"), so a time chart by quarter failed. DATE_TRUNC('quarter', ...) is native; every other granularity is unchanged.
  timeGroupedColumn(granularity, dimension) {
    if (granularity === 'quarter') {
      return `CAST(DATE_TRUNC('quarter', ${dimension}) AS DATETIME)`;
    }
    return super.timeGroupedColumn(granularity, dimension);
  }
}

// --- Security --------------------------------------------------------------
// Tokens are minted by auth/ after Keycloak login: {user_id, role, territories, exp}.
// checkAuth verifies them itself (rather than relying on dev-mode defaults) so a missing,
// expired or tampered token is always rejected.
const SECRET = process.env.CUBEJS_API_SECRET;
// What a person may read is decided by datasets and grants (blocked_cubes, blocked_members in the token), not by their role; the rules below are the ones that need no configuration: the sales facts
// are limited to the person's territories, and the proposal agent (a service account, not a person) may only read the cubes the model lists for it (`agent.cubes` in model.config.yml).
// The row-level dimensions (territory, ...): access.rls_dimension in Postgres, read once, now, while this file loads (rls_registry.js; the default file
// rls_dimensions.json when CUBE_ACCESS_PG_PASSWORD is not set). The auth service and the admin console read the same table when they start.
// A registry that cannot be read or is not valid throws here, so Cube does not start.
const RLS = require('./rls_registry').init();
// What this model says about itself (model.config.yml, beside this file): the cubes the proposal agent may read, and the cubes of this model a dataset adds to the spike model.
// No file or no key means no cubes (an agent token then reads nothing): the app knows no model.
const MODEL = (() => {
  try { return require('js-yaml').load(require('fs').readFileSync(require('path').join(__dirname, 'model.config.yml'), 'utf8')) || {}; } catch (e) { return {}; }
})();
const AGENT_CUBES = new Set((MODEL.agent && MODEL.agent.cubes) || []);
const DATASET_OVERLAY = ((MODEL.datasets && MODEL.datasets.overlay_cubes) || []).map((n) => `${n}.yml`);

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

// The SQL API (the SQL lab, lab/): a connection signs in as the user with the same Cube token the REST API takes, as the password. The token's claims become the
// security context, so every statement goes through queryRewrite below exactly like a dashboard's query: role rules, territories, blocked cubes.
async function checkSqlAuth(req, user, password) {
  let claims;
  try {
    claims = jwt.verify(String(password || ''), SECRET, { algorithms: ['HS256'] });
  } catch (e) {
    throw unauthorized();
  }
  if (!claims.user_id || !claims.role || claims.user_id !== user) {
    throw unauthorized();
  }
  return { password, securityContext: claims };
}

// The SQL API (and only it) sends a member as an object when the statement uses an expression instead of a name: COUNT(*), COUNT(DISTINCT dim), or a dimension of a joined cube
// ({ cubeName, name, expression: [...cubes the expression touches, 'return `<sql>`'] }). An object is turned back into the member names it stands for, so every rule below
// applies to it as to a named member. Only these three forms are understood; any other expression is refused for everyone but an admin, because the rules cannot see inside it.
const ADHOC = [
  [/^\$\{(\w+)\.(\w+)\}$/, (m) => [`${m[1]}.${m[2]}`]],                         // a plain member reference
  [/^COUNT\(\*\)$/i, () => []],                                                       // rows: the cubes it touches are what matter
  [/^COUNT\(DISTINCT \$\{(\w+)\.(\w+)\}\)$/i, (m) => [`${m[1]}.${m[2]}`]],
];
function expandMember(m, role) {
  if (typeof m === 'string') {
    return [m];
  }
  const expr = m && Array.isArray(m.expression) ? m.expression : null;
  if (!m || typeof m !== 'object' || !expr || expr.length < 2) {
    throw forbidden('This kind of query is not available');
  }
  const cubes = [...new Set([m.cubeName, ...expr.slice(0, -1)].filter((c) => typeof c === 'string'))];
  const sql = String(expr[expr.length - 1]).replace(/^return\s+/, '').trim().replace(/^`|`$/g, '');
  const hit = ADHOC.map(([re, fn]) => [re.exec(sql), fn]).find(([r]) => r);
  if (!hit) {
    if (role === 'admin') {
      return cubes.map((c) => `${c}.__expression`);
    }
    throw forbidden('This kind of expression is not available: use a measure (MEASURE(name)), a dimension, or COUNT');
  }
  return [...hit[1](hit[0]), ...cubes.map((c) => `${c}.__rows`)];
}

// Every member the query touches, including inside nested and/or filters.
function membersOf(query, role) {
  const out = [];
  const add = (m) => expandMember(m, role).forEach((x) => out.push(x));
  (query.measures || []).forEach(add);
  (query.dimensions || []).forEach(add);
  (query.timeDimensions || []).forEach((t) => add(t.dimension));
  (query.segments || []).forEach(add);
  // order is {member: 'asc'} or [[member, 'asc'], ...]; ordering by a hidden measure leaks its ranking.
  const order = query.order || [];
  (Array.isArray(order) ? order.map((o) => o[0]) : Object.keys(order)).forEach(add);
  const walk = (filters) => (filters || []).forEach((f) => {
    if (f.member) add(f.member);
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
  const members = membersOf(query, sc.role);
  const cubes = new Set(members.map((m) => m.split('.')[0]));

  // Datasets (admin console): a cube that is in a dataset the person has no grant on. The auth service puts the list in the token; no list, nothing blocked.
  // The proposal agent is a service account with its own fixed list of cubes (below); datasets are for people.
  const blockedCubes = sc.role !== 'agent' && Array.isArray(sc.blocked_cubes) ? sc.blocked_cubes : [];
  const hidden = [...cubes].find((c) => blockedCubes.includes(c));
  if (hidden) {
    throw forbidden(`'${hidden}' is in a dataset you have no access to`);
  }
  // ... and single fields a dataset holds (profit, say): the same rule for a member named in the query or inside an expression.
  const blockedMembers = sc.role !== 'agent' && Array.isArray(sc.blocked_members) ? sc.blocked_members : [];
  const hiddenField = members.find((m) => blockedMembers.includes(m));
  if (hiddenField) {
    throw forbidden(`'${hiddenField}' is in a dataset you have no access to`);
  }

  if (sc.role === 'admin') {
    return query;
  }
  if (sc.role === 'agent') {
    // the proposal agent: both inventory cubes in full, nothing else, and it cannot write
    if (![...cubes].every((c) => AGENT_CUBES.has(c)) || ![...cubes].some((c) => c !== 'products')) {
      throw forbidden('Not available for your role');
    }
    return query;
  }

  // The token was made from the same registry as the one enforced here: after a change to access.rls_dimension, an auth service restarted without Cube (or the
  // other way round) would hand out values for a dimension that is not filtered on. A token from before `rls_version` existed has none and is let through.
  if (sc.rls_version !== undefined && sc.rls_version !== RLS.version) {
    throw forbidden('The row-level dimensions changed: restart the auth service and Cube together, then sign in again');
  }
  // Row-level security (access.rls_dimension): for each dimension whose cubes the query touches, only the person's own values. Dimensions are ANDed; the values of one are ORed.
  // The token's `rls` holds the values per dimension (an older token only has `territories`). Nobody listed for a `deny` dimension gets nothing from its cubes.
  for (const dim of RLS.dimensions) {
    if (!dim.cubes.some((c) => cubes.has(c))) continue;
    const mine = sc.rls && Array.isArray(sc.rls[dim.id]) ? sc.rls[dim.id] : (dim.id === 'territory' && Array.isArray(sc.territories) ? sc.territories : []);
    if (mine.length === 0) {
      if (dim.when_empty === 'allow') continue;
      throw forbidden(dim.empty_message || `No ${dim.id} values assigned`);
    }
    // ANDed with whatever the client asked for, so asking for another value yields nothing.
    query.filters = [...(query.filters || []), { member: dim.member, operator: 'equals', values: mine }];
  }
  return query;
}

// --- Dataset ---------------------------------------------------------------
// DATASET=live (the default) serves cube/model on the live mart. DATASET=250m serves the 500M-tuned model (year-partitioned
// rollups, hourly refresh: the data does not move) from spike/cube/model plus the two inventory cubes of cube/model, all
// read from mart_250m instead of mart, into their own pre-aggregation schema so the live rollups are kept.
// The files are re-pointed at load time (mart. -> mart_250m.), so there is no second copy of any model to keep in sync.
// `both` (two Cubes, see docker-compose.yml) makes this one the live Cube; the 250m one is started with DATASET=250m.
const DATASET = (process.env.DATASET || 'live').toLowerCase();
const SUFFIX = (DATASET === 'live' || DATASET === 'both') ? '' : `_${DATASET}`;

function datasetRepository() {
  const fs = require('fs');
  const path = require('path');
  const spike = path.join(process.env.SPIKE_MODEL_DIR || '/cube/spike-model', 'cubes');
  const own = path.join(__dirname, 'model', 'cubes');
  const retarget = (text) => text.replace(/\bmart\./g, `mart${SUFFIX}.`);
  const read = (dir, names) => names.map((n) => ({ fileName: `cubes/${n}`, content: retarget(fs.readFileSync(path.join(dir, n), 'utf8')) }));
  return {
    localPath: () => __dirname,
    dataSchemaFiles: async () => [
      ...read(spike, fs.readdirSync(spike).filter((n) => n.endsWith('.yml'))),
      ...read(own, DATASET_OVERLAY),
    ],
  };
}

module.exports = {
  // The StarRocks dialect fix is for StarRocks (it speaks the MySQL protocol); any other database (a model on Postgres) keeps Cube's own dialect.
  ...(process.env.CUBEJS_DB_TYPE === 'mysql' && { dialectFactory: () => StarRocksQuery }),
  checkAuth,
  checkSqlAuth,
  queryRewrite,
  ...(SUFFIX && {
    repositoryFactory: datasetRepository,
    preAggregationsSchema: `${process.env.CUBEJS_PRE_AGGREGATIONS_SCHEMA || 'dev_pre_aggregations'}${SUFFIX}`,
  }),
};
