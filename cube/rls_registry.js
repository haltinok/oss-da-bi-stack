// The row-level dimension registry (PLAN-rls-registry-db.md), as Cube reads it: once, while cube.js loads.
//
// With CUBE_ACCESS_PG_PASSWORD set it is read from Postgres, access.rls_dimension, through the read-only login access_cube. The read runs in a child process
// (rls_registry_load.js) so that cube.js stays synchronous and queryRewrite never waits on a database. Without the password, the default file
// rls_dimensions.json is used. A registry that cannot be read, or is not valid, throws: Cube does not start rather than run on half a list.
//
// `normalize` and `version` mirror auth/rls_registry.py (dashboards/tests/test_rls_dimensions.py checks they give the same version).
const crypto = require('crypto');
const path = require('path');

const ID = /^[a-z][a-z0-9_]{0,39}$/;
const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const MEMBER = /^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$/;
const VALUE_KINDS = ['seed_regions', 'list', 'cube'];
const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const fail = (msg) => { const e = new Error(msg); e.name = 'RegistryError'; throw e; };

/** The registry in its canonical form, or a RegistryError naming the first problem (same rules as rls_registry.normalize in Python). */
function normalize(dims) {
  if (!Array.isArray(dims) || dims.length === 0) fail('the registry has no dimensions (an empty list would leave every row open)');
  const seen = new Set();
  return dims.map((d, i) => {
    let where = `dimension ${i + 1}`;
    if (!isObject(d)) fail(`${where}: not an object`);
    if (typeof d.id !== 'string' || !ID.test(d.id)) fail(`${where}: id must be lower-case letters, digits and _ (got ${JSON.stringify(d.id)})`);
    where = `dimension '${d.id}'`;
    if (seen.has(d.id)) fail(`${where}: the id is used twice`);
    seen.add(d.id);
    if (typeof d.member !== 'string' || !MEMBER.test(d.member)) fail(`${where}: member must be cube.field (got ${JSON.stringify(d.member)})`);
    if (!Array.isArray(d.cubes) || !d.cubes.length || !d.cubes.every((c) => typeof c === 'string' && NAME.test(c))) fail(`${where}: cubes must be a non-empty list of cube names`);
    if (d.when_empty !== 'deny' && d.when_empty !== 'allow') fail(`${where}: when_empty must be deny or allow (got ${JSON.stringify(d.when_empty)})`);
    let values = d.values === undefined ? { kind: 'cube' } : d.values;
    if (!isObject(values) || !VALUE_KINDS.includes(values.kind)) fail(`${where}: values.kind must be one of ${VALUE_KINDS.join(', ')}`);
    if (values.kind === 'list') {
      if (!Array.isArray(values.values) || !values.values.length || !values.values.every((v) => typeof v === 'string')) fail(`${where}: a values list needs at least one value, all text`);
      values = { kind: 'list', values: [...values.values] };
    } else values = { kind: values.kind };
    const seed = d.seed === undefined ? false : d.seed;
    if (typeof seed !== 'boolean') fail(`${where}: seed must be true or false`);
    const labels = d.labels == null ? {} : d.labels;
    if (!isObject(labels) || !Object.values(labels).every((v) => typeof v === 'string')) fail(`${where}: labels must map a language to a text`);
    const message = d.empty_message == null ? '' : d.empty_message;
    if (typeof message !== 'string') fail(`${where}: empty_message must be text`);
    return { id: d.id, member: d.member, cubes: [...d.cubes], when_empty: d.when_empty, values, seed, labels: { ...labels }, empty_message: message };
  });
}

/** JSON with every object's keys sorted and no spaces: what Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) writes. */
function canonical(v) {
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (isObject(v)) return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`;
  return JSON.stringify(v);
}

/** A short hash of the canonical registry; the auth service puts the same one in the token. */
const version = (dims) => crypto.createHash('sha256').update(canonical(dims), 'utf8').digest('hex').slice(0, 16);

/** A row of `select id, member, cubes, when_empty, values_source, seed, labels, empty_message` as a registry entry. */
const fromRow = (r) => ({ id: r.id, member: r.member, cubes: r.cubes || [], when_empty: r.when_empty, values: r.values_source, seed: r.seed, labels: r.labels, empty_message: r.empty_message });

/** { dimensions, source } from the database (CUBE_ACCESS_PG_PASSWORD set) or the default file. Throws on any failure. */
function load(env = process.env) {
  const pw = env.CUBE_ACCESS_PG_PASSWORD || '';
  if (!pw || pw === 'REPLACE_ME') {
    return { dimensions: normalize(require('./rls_dimensions.json').dimensions), source: 'file' };
  }
  const { execFileSync } = require('child_process');
  const wait = Number(env.RLS_REGISTRY_WAIT || 60);
  let out;
  try {
    out = execFileSync(process.execPath, [path.join(__dirname, 'rls_registry_load.js')], { env, encoding: 'utf8', timeout: (wait + 20) * 1000, stdio: ['ignore', 'pipe', 'inherit'] });
  } catch (e) {
    throw new Error(`cannot read the row-level dimensions from access.rls_dimension (${e.status != null ? `the loader exited with ${e.status}` : e.message}); Cube does not start without them`);
  }
  return { dimensions: normalize(JSON.parse(out).map(fromRow)), source: 'database' };
}

// What cube.js enforces. Filled once by init(); the tests may replace `dimensions` (it is read at query time, through this object).
const state = { dimensions: [], version: '', source: '' };

function init(env = process.env) {
  const { dimensions, source } = load(env);
  Object.assign(state, { dimensions, source, version: version(dimensions) });
  console.log(`rls registry: ${dimensions.length} dimension(s) from the ${source} (${dimensions.map((d) => d.id).join(', ')}), version ${state.version}`);
  return state;
}

module.exports = { normalize, canonical, version, fromRow, load, init, state };
