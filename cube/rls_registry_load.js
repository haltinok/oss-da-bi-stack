// Prints the rows of access.rls_dimension as JSON on stdout, for rls_registry.js (which runs this in a child process while cube.js loads, so it can wait synchronously).
// Retries a connection or query error for RLS_REGISTRY_WAIT seconds (Postgres may start after Cube), then exits 1. Uses the `pg` client the Cube image ships.
//   CUBE_ACCESS_PG_HOST (postgres), CUBE_ACCESS_PG_PORT (5432), CUBE_ACCESS_PG_DB (postgres), CUBE_ACCESS_PG_USER (access_cube), CUBE_ACCESS_PG_PASSWORD
const { Client } = require('pg');

const SELECT = 'select id, member, cubes, when_empty, values_source, seed, labels, empty_message from access.rls_dimension order by position, id';
const env = process.env;
const deadline = Date.now() + Number(env.RLS_REGISTRY_WAIT || 60) * 1000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  for (;;) {
    const client = new Client({
      host: env.CUBE_ACCESS_PG_HOST || 'postgres', port: Number(env.CUBE_ACCESS_PG_PORT || 5432), database: env.CUBE_ACCESS_PG_DB || 'postgres',
      user: env.CUBE_ACCESS_PG_USER || 'access_cube', password: env.CUBE_ACCESS_PG_PASSWORD, connectionTimeoutMillis: 5000, query_timeout: 10000,
    });
    try {
      await client.connect();
      const { rows } = await client.query(SELECT);
      process.stdout.write(JSON.stringify(rows));
      await client.end();
      return;
    } catch (e) {
      await client.end().catch(() => {});
      if (Date.now() >= deadline) {
        console.error(`rls registry: cannot read access.rls_dimension: ${e.message}`);
        process.exit(1);
      }
      console.error(`rls registry: cannot read access.rls_dimension yet (${e.message}); retrying`);
      await sleep(2000);
    }
  }
})();
