// The 250m dataset's model loader (cube/cube.js): `node cube/tests/dataset.test.js`, no Cube or database needed.
const assert = require('assert');
const path = require('path');

process.env.CUBEJS_API_SECRET = 'x';
process.env.DATASET = '250m';
process.env.SPIKE_MODEL_DIR = path.join(__dirname, '..', '..', 'spike', 'cube', 'model');
const cfg = require('../cube.js');

(async () => {
  assert.strictEqual(typeof cfg.repositoryFactory, 'function', '250m sets a repositoryFactory');
  assert.strictEqual(cfg.preAggregationsSchema, 'dev_pre_aggregations_250m', 'its own rollup schema, the live one is kept');
  const files = await cfg.repositoryFactory().dataSchemaFiles();
  const names = files.map((f) => f.fileName).sort();
  assert.deepStrictEqual(names, [
    'cubes/customers.yml', 'cubes/dates.yml', 'cubes/internet_sales.yml', 'cubes/inventory_health.yml', 'cubes/offer_performance.yml',
    'cubes/products.yml', 'cubes/reseller_sales.yml', 'cubes/territories.yml']);
  for (const f of files) {
    assert(!/\bmart\./.test(f.content), `${f.fileName} still reads the live mart`);
    assert(!/\bmart_250m\.mart/.test(f.content));
  }
  const by = Object.fromEntries(files.map((f) => [f.fileName, f.content]));
  assert(by['cubes/internet_sales.yml'].includes('mart_250m.fact_internet_sales'));
  assert(by['cubes/inventory_health.yml'].includes('mart_250m.inventory_health'));
  assert(by['cubes/dates.yml'].includes('mart_250m.dim_date'));
  // the 500M-tuned model: year partitions with an incremental window, not the live 5-minute refresh
  assert(/partition_granularity: year/.test(by['cubes/internet_sales.yml']));
  assert(!/data_version/.test(by['cubes/internet_sales.yml']));
  console.log('dataset loader ok:', names.length, 'files, all on mart_250m');

  // live: nothing changes (no repositoryFactory, no rollup schema override)
  delete require.cache[require.resolve('../cube.js')];
  process.env.DATASET = 'live';
  const live = require('../cube.js');
  assert.strictEqual(live.repositoryFactory, undefined);
  assert.strictEqual(live.preAggregationsSchema, undefined);
  console.log('live: default repository and rollup schema');
})().catch((e) => { console.error(e); process.exit(1); });
