// Data source for the existing dashboard: signs in through Keycloak (authorization code + PKCE),
// swaps the Keycloak token for a 15-minute Cube token, and answers the page's two calls,
// /api/meta and /api/dashboard, with Cube queries (via @cubejs-client/core) instead of SQL.
// The shapes returned are exactly those of the former Postgres-backed dashboard/app.py, so app.js is unchanged apart
// from a one-line hook in getJSON() and null-safe handling of hidden profit figures.
import { createCubeClient } from "./cube-client.mjs";

const C = window.STACK;

function showWho(session) {
  if (document.getElementById("who")) return;
  const who = document.createElement("div");
  who.id = "who";
  who.className = "who";
  who.title = `Signed in as ${session.user}, role ${session.role}`;
  who.innerHTML = `${session.user} · <a href="#" id="signout">Sign out</a>`;
  (document.querySelector("header.top .tools") || document.querySelector("header.top"))?.append(who);
  document.getElementById("signout").addEventListener("click", (e) => {
    e.preventDefault();
    client.signOut();
  });
}

// ------------------------------------------------------------------ Cube queries
// Which mart the page reads: the live one, or (when the stack offers it, see nginx.conf.template) the 250M benchmark
// copy. Chosen with ?dataset=250m, remembered per browser; a benchmark dataset is read-only (no inventory actions).
const DATASETS = C.datasets || [{ id: "live", label: "Live (simulator)", mart: "mart", cube: C.cube }];
const keep = { get: () => { try { return localStorage.getItem("dataset"); } catch { return null; } }, set: (v) => { try { localStorage.setItem("dataset", v); } catch { /* ignore */ } } };
const wanted = new URLSearchParams(location.search).get("dataset") || keep.get();
const dataset = DATASETS.find((d) => d.id === wanted) || DATASETS[0];
keep.set(dataset.id);
window.dashboardData.dataset = dataset;
window.dashboardData.datasets = DATASETS;
const client = createCubeClient({
  stack: C, apiUrl: dataset.cube,
  onSession(session) {
    window.dashboardData.noProfit = session.role === "rep"; // profit/margin are not available to reps
    window.dashboardData.role = session.role;
    showWho(session);
  },
});
const { run } = client;
const CH = { Internet: "internet_sales", Reseller: "reseller_sales" };
const num = (v) => (v == null ? null : Number(v));

const channels = (f) => (f.channel ? [f.channel] : Object.keys(CH));
const profit = () => !window.dashboardData.noProfit;
// Orders. `orders_placed` (each order counted once, on its first line) is exact for any grouping or
// filter on order-level attributes and additive, so a plain rollup serves it even under a multi-region
// security filter. It is wrong as soon as products are involved (an order has several categories), so
// then the exact distinct count is needed, which only a scan of the fact can answer: slow. Panels that
// need it therefore run in two stages: first everything except orders (fast, drawn at once), then the
// same query with the exact count, which redraws the panel when it finally returns.
const orderMeasure = { placed: "orders_placed", exact: "orders", none: null };
const measures = (ch, mode) => [
  `${CH[ch]}.revenue`, ...(profit() ? [`${CH[ch]}.gross_profit`] : []),
  ...(orderMeasure[mode] ? [`${CH[ch]}.${orderMeasure[mode]}`] : []), `${CH[ch]}.units`,
];
const figures = (ch, r) => ({
  revenue: num(r[`${CH[ch]}.revenue`]), gross_profit: profit() ? num(r[`${CH[ch]}.gross_profit`]) : null,
  orders: num(r[`${CH[ch]}.orders`] ?? r[`${CH[ch]}.orders_placed`]), units: num(r[`${CH[ch]}.units`]),
});
const nz = (a, b) => (a == null || b == null ? null : a + b);
const add = (a, b) => ({
  revenue: a.revenue + b.revenue, gross_profit: nz(a.gross_profit, b.gross_profit),
  orders: nz(a.orders, b.orders), units: a.units + b.units,
});
const ZERO = { revenue: 0, gross_profit: 0, orders: 0, units: 0 };

// Page filters -> Cube filters. `skip` lists filters a cross-filtering panel ignores.
function filters(f, skip = []) {
  const out = [];
  const eq = (member, value) => out.push({ member, operator: "equals", values: [String(value)] });
  if (f.fy && !skip.includes("fy")) eq("dates.fiscal_year", f.fy);
  if (f.group && !skip.includes("group")) eq("territories.group_name", f.group);
  if (f.region && !skip.includes("region")) eq("territories.region", f.region);
  if (f.category && !skip.includes("category")) eq("products.category", f.category);
  if (f.subcategory && !skip.includes("subcategory")) eq("products.subcategory", f.subcategory);
  return out;
}

const day = (iso) => iso.slice(0, 10);
const addDays = (iso, n) => { const d = new Date(`${day(iso)}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };

// Run `build(mode)` once per mode and hand each result to emit() the moment it arrives. With two modes
// the second (exact orders) is a late refinement: its failure leaves the first result in place.
async function staged(modes, build, emit, pending) {
  for (let i = 0; i < modes.length; i++) {
    const last = i === modes.length - 1;
    if (i === 0 && modes.length > 1) pending.n++;
    let patch;
    try {
      patch = await build(modes[i]);
    } catch (e) {
      if (i > 0 && e?.name !== "AbortError") { pending.n--; emit({}); return; } // late stage failed: keep the quick result
      if (modes.length > 1 && i === 0) pending.n--;
      throw e;
    }
    if (last && modes.length > 1) pending.n--;
    emit(patch);
  }
}

async function dashboard(f, signal, update, skipFeed = false) {
  const chans = channels(f);
  const out = {};
  const productFilter = !!(f.category || f.subcategory);
  // `pending.n` > 0 shows "…" on the Orders / Avg order value tiles: with a product filter they wait for lateOrders().
  const pending = { n: productFilter ? 1 : 0 };
  const emit = (patch) => {
    if (signal?.aborted) return;
    Object.assign(out, patch, { ordersPending: pending.n > 0 });
    update?.({ ...patch, ordersPending: pending.n > 0 });
  };
  const perChannel = (fn) => Promise.all(chans.map((ch) => fn(ch).then((rows) => ({ ch, rows }))));
  // With a product filter the order count needs the exact distinct count: kpis, monthly and territories
  // draw without it at once, and lateOrders() fills it in from ONE scan per channel (below).
  const orderModes = productFilter ? ["none"] : ["placed"];

  const kpis = () => staged(orderModes, async (mode) => {
    const res = await perChannel((ch) => run({
      measures: measures(ch, mode),
      dimensions: f.fy ? ["dates.fiscal_year"] : [],
      filters: [...filters(f, ["fy"]),
        ...(f.fy ? [{ member: "dates.fiscal_year", operator: "equals", values: [String(f.fy), String(f.fy - 1)] }] : [])],
    }, signal));
    let current = null, previous = null;
    for (const { ch, rows } of res) {
      for (const r of rows) {
        const fig = figures(ch, r);
        if (f.fy && Number(r["dates.fiscal_year"]) === Number(f.fy) - 1) previous = add(previous || ZERO, fig);
        else current = add(current || ZERO, fig);
      }
    }
    return { kpis: { current, previous } };
  }, emit, pending);

  const monthly = () => staged(orderModes, async (mode) => {
    const res = await perChannel((ch) => run({
      measures: measures(ch, mode), filters: filters(f),
      timeDimensions: [{ dimension: `${CH[ch]}.order_date`, granularity: "month" }],
      order: { [`${CH[ch]}.order_date`]: "asc" },
    }, signal));
    return { monthly: res.flatMap(({ ch, rows }) => rows.map((r) => ({
      month: day(r[`${CH[ch]}.order_date.month`]), channel: ch, ...figures(ch, r),
    }))).sort((a, b) => (a.month < b.month ? -1 : a.month > b.month ? 1 : a.channel < b.channel ? -1 : 1)) };
  }, emit, pending);

  // Orders per category = distinct orders containing it, never additive: always two stages.
  const mixLate = { n: 0 };   // the mix table's own late stage; it must not put "…" on the KPI tiles
  const mix = () => staged(["none", "exact"], async (mode) => {
    const res = await perChannel((ch) => run({
      measures: measures(ch, mode), dimensions: ["products.category", "products.subcategory"],
      filters: filters(f, ["category", "subcategory"]),
    }, signal));
    const m = new Map();
    for (const { ch, rows } of res) {
      for (const r of rows) {
        const key = `${r["products.category"]}\u0000${r["products.subcategory"]}`;
        const cur = m.get(key) || { category: r["products.category"], subcategory: r["products.subcategory"], ...ZERO };
        m.set(key, { ...cur, ...add(cur, figures(ch, r)) });
      }
    }
    return { mix: [...m.values()].sort((a, b) => b.revenue - a.revenue) };
  }, emit, mixLate);

  const products = async () => {
    const res = await perChannel((ch) => run({
      measures: [`${CH[ch]}.revenue`, ...(profit() ? [`${CH[ch]}.gross_profit`] : []), `${CH[ch]}.units`],
      dimensions: ["products.name", "products.category"], filters: filters(f),
    }, signal));
    const m = new Map();
    for (const { ch, rows } of res) {
      for (const r of rows) {
        const name = r["products.name"];
        const cur = m.get(name) || { product_name: name, category: r["products.category"], revenue: 0, internet: 0, reseller: 0, gross_profit: 0, units: 0 };
        const rev = num(r[`${CH[ch]}.revenue`]);
        const gp = profit() ? num(r[`${CH[ch]}.gross_profit`]) : null;
        m.set(name, { ...cur, revenue: cur.revenue + rev, [ch.toLowerCase()]: cur[ch.toLowerCase()] + rev,
          gross_profit: nz(cur.gross_profit, gp), units: cur.units + num(r[`${CH[ch]}.units`]) });
      }
    }
    emit({ top_products: [...m.values()].sort((a, b) => b.revenue - a.revenue).slice(0, 10) });
  };

  const territories = () => staged(orderModes, async (mode) => {
    const res = await perChannel((ch) => run({
      measures: [`${CH[ch]}.revenue`, ...(profit() ? [`${CH[ch]}.gross_profit`] : []),
        ...(orderMeasure[mode] ? [`${CH[ch]}.${orderMeasure[mode]}`] : [])],
      dimensions: ["territories.group_name", "territories.region"], filters: filters(f, ["group", "region"]),
    }, signal));
    const m = new Map();
    for (const { ch, rows } of res) {
      for (const r of rows) {
        const key = r["territories.region"];
        const cur = m.get(key) || { grp: r["territories.group_name"], region: key, revenue: 0, internet: 0, reseller: 0, gross_profit: 0, orders: 0 };
        const rev = num(r[`${CH[ch]}.revenue`]);
        const gp = profit() ? num(r[`${CH[ch]}.gross_profit`]) : null;
        m.set(key, { ...cur, revenue: cur.revenue + rev, [ch.toLowerCase()]: cur[ch.toLowerCase()] + rev,
          gross_profit: nz(cur.gross_profit, gp),
          orders: nz(cur.orders, num(r[`${CH[ch]}.orders`] ?? r[`${CH[ch]}.orders_placed`])) });
      }
    }
    return { territories: [...m.values()].sort((a, b) => b.revenue - a.revenue) };
  }, emit, pending);

  // Newest orders ignore every page filter (row-level security still applies server-side). Find the newest day from the daily rollup (without any
  // product filter, which that rollup does not carry), then read only the last week (one or two month
  // partitions) instead of aggregating every order. A product filter may leave fewer than 8 orders in
  // that week; then look back further (still only a few partitions).
  const latest = async () => {
    const res = await Promise.all(Object.keys(CH).map(async (ch) => ({ ch, rows: await (async (ch) => {
      const c = CH[ch];
      const last = await run({ measures: [`${c}.revenue`], filters: [],
        timeDimensions: [{ dimension: `${c}.order_date`, granularity: "day" }],
        order: { [`${c}.order_date`]: "desc" }, limit: 1 }, signal);
      if (!last.length) return [];
      const end = day(last[0][`${c}.order_date.day`]);
      const window = (days) => run({
        measures: [`${c}.lines`, `${c}.revenue`],
        dimensions: [`${c}.order_number`, `${c}.order_date`, "territories.region", `${c}.order_status`],
        filters: [],
        timeDimensions: [{ dimension: `${c}.order_date`, dateRange: [addDays(end, -days), end] }],
        order: { [`${c}.order_date`]: "desc", [`${c}.order_number`]: "desc" }, limit: 8,
      }, signal);
      const rows = await window(6);
      return rows;
    })(ch) })));
    emit({ latest_orders: res.flatMap(({ ch, rows }) => rows.map((r) => ({
      sales_order_number: r[`${CH[ch]}.order_number`], channel: ch,
      order_date: r[`${CH[ch]}.order_date`].replace(/\.\d+$/, ""), region: r["territories.region"],
      order_status: num(r[`${CH[ch]}.order_status`]), lines: num(r[`${CH[ch]}.lines`]), revenue: num(r[`${CH[ch]}.revenue`]),
    }))).sort((a, b) => (a.order_date === b.order_date ? (a.sales_order_number < b.sales_order_number ? 1 : -1) : a.order_date < b.order_date ? 1 : -1)).slice(0, 8) });
  };

  // An order has exactly one month, territory and channel, so exact orders (product filter only) grouped by
  // month x region are additive over any of them: one query per channel feeds the KPI tile, the monthly
  // series and the territory table, each summed under its own page filters. Eight scans become two.
  const lateOrders = async () => {
    try {
      const res = await perChannel((ch) => run({
        measures: [`${CH[ch]}.orders`],
        dimensions: ["territories.group_name", "territories.region"],
        timeDimensions: [{ dimension: `${CH[ch]}.order_date`, granularity: "month" }],
        filters: filters({ category: f.category, subcategory: f.subcategory }),
      }, signal));
      const fyOf = (iso) => { const [y, m] = iso.split("-").map(Number); return m >= 7 ? y + 1 : y; };
      const rows = res.flatMap(({ ch, rows: rs }) => rs.map((r) => ({
        ch, month: day(r[`${CH[ch]}.order_date.month`]), grp: r["territories.group_name"], region: r["territories.region"],
        orders: num(r[`${CH[ch]}.orders`]),
      })));
      const sum = (pred) => rows.filter(pred).reduce((s, r) => s + r.orders, 0);
      const region = (r) => (!f.group || r.grp === f.group) && (!f.region || r.region === f.region);
      const patch = {};
      if (out.kpis) {
        const cur = out.kpis.current, prev = out.kpis.previous;
        patch.kpis = {
          current: cur && { ...cur, orders: sum((r) => region(r) && (!f.fy || fyOf(r.month) === Number(f.fy))) },
          previous: prev && { ...prev, orders: sum((r) => region(r) && fyOf(r.month) === Number(f.fy) - 1) },
        };
      }
      if (out.monthly) {
        patch.monthly = out.monthly.map((m) => ({ ...m, orders: sum((r) => region(r) && r.ch === m.channel && r.month === m.month) }));
      }
      if (out.territories) {
        patch.territories = out.territories.map((t) => ({ ...t, orders: sum((r) => r.region === t.region && (!f.fy || fyOf(r.month) === Number(f.fy))) }));
      }
      pending.n--;
      emit(patch);
    } catch (e) {
      pending.n--;
      if (e?.name === "AbortError") throw e;
      emit({}); // the orders figures stay "—"; the rest of the page is unaffected
    }
  };

  // Every panel runs on its own and draws when it is ready. One failing panel must not blank the rest.
  const kp = kpis(), mp = monthly(), tp = territories();
  const late = productFilter ? Promise.all([kp, mp, tp]).then(lateOrders) : null;
  const results = await Promise.allSettled([kp, mp, mix(), products(), tp, ...(skipFeed ? [] : [latest()]), ...(late ? [late] : [])]);
  const failed = results.find((r) => r.status === "rejected");
  for (const r of results) if (r.status === "rejected" && r.reason?.name !== "AbortError") console.warn("panel query failed:", r.reason?.message || r.reason);
  if (failed) {
    if (failed.reason?.name === "AbortError" || signal?.aborted) throw failed.reason;
    if (!Object.keys(out).length) throw failed.reason;      // nothing at all loaded: show the error
  }
  return { ...out, ordersPending: false, generated_at: new Date().toISOString() };
}

async function meta(signal) {
  const [years, terr, cats] = await Promise.all([
    Promise.all(Object.values(CH).map((c) => run({ measures: [`${c}.lines`], dimensions: ["dates.fiscal_year"] }, signal))),
    run({ dimensions: ["territories.group_name", "territories.region"] }, signal),
    run({ dimensions: ["products.category", "products.subcategory"] }, signal),
  ]);
  const fiscal = [...new Set(years.flat().map((r) => Number(r["dates.fiscal_year"])))].sort((a, b) => a - b);
  const subs = cats.filter((r) => r["products.subcategory"] !== "Uncategorized")
    .map((r) => ({ category: r["products.category"], subcategory: r["products.subcategory"] }))
    .sort((a, b) => a.category.localeCompare(b.category) || a.subcategory.localeCompare(b.subcategory));
  const lines = (await Promise.all(Object.values(CH).map((c) => run({ measures: [`${c}.lines`] }, signal))))
    .reduce((s, rows, i) => s + num(rows[0]?.[`${Object.values(CH)[i]}.lines`] || 0), 0);
  return {
    fiscal_years: fiscal,
    territories: terr.map((r) => ({ grp: r["territories.group_name"], region: r["territories.region"] }))
      .sort((a, b) => a.grp.localeCompare(b.grp) || a.region.localeCompare(b.region)),
    categories: [...new Set(cats.map((r) => r["products.category"]).filter((c) => c !== "Uncategorized"))].sort(),
    subcategories: subs,
    last_order_at: null,
    fact_rows: lines,
    generated_at: new Date().toISOString(),
  };
}


// ------------------------------------------------------------------ inventory (reorders and overstock)
// Not territory-bound and not filtered: it ignores every page filter, and the role decides what is asked
// for (cube/cube.js enforces the same split, so a tampered page cannot see more than its role allows).
const INV = "inventory_health";

// ------------------------------------------------------------------ inventory actions service
// The same Keycloak access token as the auth service gets; the service checks the role and every rule again.
async function actionsCall(method, path, body) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const kc = await client.keycloak();
    const res = await fetch(`${C.actions}${path}`, {
      method, headers: { Authorization: `Bearer ${kc.access}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401 && attempt === 0) { client.dropKeycloakToken(); continue; }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? "The request was malformed" : `HTTP ${res.status}`);
    return data;
  }
}

const BAND_OF = { 10: "1-10%", 20: "11-20%", 30: "21-30%", 40: "over 30%" };

async function inventory(signal) {
  const role = client.session().role;
  const out = {};
  const q = [];
  if (role === "admin" || role === "purchasing") {
    q.push(run({
      measures: [`${INV}.items_at_risk`, `${INV}.stockout_items`, `${INV}.reorder_items`, `${INV}.suggested_order_value_total`],
    }, signal).then((r) => {
      const x = r[0] || {};
      out.reorder_kpis = { at_risk: num(x[`${INV}.items_at_risk`]) || 0, stockouts: num(x[`${INV}.stockout_items`]) || 0,
        reorder_now: num(x[`${INV}.reorder_items`]) || 0, order_value: num(x[`${INV}.suggested_order_value_total`]) || 0 };
    }));
    const dims = ["key", "product_name", "status", "replenishment_type", "vendor_name", "on_hand", "on_order", "daily_demand",
      "days_of_cover", "lead_time_days", "suggested_order_qty", "suggested_order_value", "min_order_qty", "max_order_qty", "reason"].map((d) => `${INV}.${d}`);
    q.push(run({
      dimensions: dims,
      filters: [{ member: `${INV}.status`, operator: "equals", values: ["stockout", "reorder_now"] }],
      order: [[`${INV}.suggested_order_value`, "desc"], [`${INV}.days_of_cover`, "asc"]], limit: 500,
    }, signal).then((rows) => {
      out.reorder = rows.map((r) => ({
        id: num(r[`${INV}.key`]), min_qty: num(r[`${INV}.min_order_qty`]), max_qty: num(r[`${INV}.max_order_qty`]),
        product: r[`${INV}.product_name`], status: r[`${INV}.status`], type: r[`${INV}.replenishment_type`],
        vendor: r[`${INV}.vendor_name`], on_hand: num(r[`${INV}.on_hand`]), on_order: num(r[`${INV}.on_order`]),
        daily_demand: num(r[`${INV}.daily_demand`]), days_of_cover: num(r[`${INV}.days_of_cover`]),
        lead_time_days: num(r[`${INV}.lead_time_days`]), qty: num(r[`${INV}.suggested_order_qty`]),
        value: num(r[`${INV}.suggested_order_value`]), reason: r[`${INV}.reason`],
      }));
    }));
  }
  if (role === "admin" || role === "marketing") {
    q.push(run({
      measures: [`${INV}.overstock_items`, `${INV}.dead_stock_items`, `${INV}.excess_value_total`, `${INV}.excess_units_total`],
    }, signal).then((r) => {
      const x = r[0] || {};
      out.excess_kpis = { items: num(x[`${INV}.overstock_items`]) || 0, dead: num(x[`${INV}.dead_stock_items`]) || 0,
        value: num(x[`${INV}.excess_value_total`]) || 0, units: num(x[`${INV}.excess_units_total`]) || 0 };
    }));
    const dims = ["key", "product_name", "status", "on_hand", "days_of_cover", "excess_units", "excess_value", "suggested_discount_pct", "reason"]
      .map((d) => `${INV}.${d}`);
    q.push(run({
      dimensions: dims,
      filters: [{ member: `${INV}.status`, operator: "equals", values: ["overstock", "dead_stock"] }],
      order: [[`${INV}.excess_value`, "desc"]], limit: 500,
    }, signal).then((rows) => {
      out.overstock = rows.map((r) => ({
        id: num(r[`${INV}.key`]),
        product: r[`${INV}.product_name`], status: r[`${INV}.status`], on_hand: num(r[`${INV}.on_hand`]),
        days_of_cover: num(r[`${INV}.days_of_cover`]), excess_units: num(r[`${INV}.excess_units`]),
        excess_value: num(r[`${INV}.excess_value`]), discount_pct: num(r[`${INV}.suggested_discount_pct`]),
        reason: r[`${INV}.reason`],
      }));
    }));
    // Evidence per discount band: how past offers at that depth moved the products sold under them. One row
    // per offer, reduced to the median per band here: a single offer with a tiny baseline can show a 60x lift
    // that would swamp an average.
    q.push(run({
      dimensions: ["offer_performance.key", "offer_performance.discount_band", "offer_performance.lift"], limit: 500,
    }, signal).then((rows) => {
      const by = {};
      for (const r of rows) {
        const e = (by[r["offer_performance.discount_band"]] ||= { offers: 0, lifts: [] });
        const lift = num(r["offer_performance.lift"]);
        if (lift != null) { e.offers++; e.lifts.push(lift); }
      }
      out.offer_evidence = Object.fromEntries(Object.entries(by).map(([band, e]) => {
        const l = e.lifts.sort((x, y) => x - y), m = Math.floor(l.length / 2);
        return [band, { offers: e.offers, lift: l.length ? (l.length % 2 ? l[m] : (l[m - 1] + l[m]) / 2) : null }];
      }));
    }));
  }
  await Promise.all(q);
  out.band_of = BAND_OF;
  out.generated_at = new Date().toISOString();
  return out;
}

// ------------------------------------------------------------------ the endpoints the page calls
await client.token(); // signs in (redirecting if needed) before the first request
window.__dashboardDataReady({
  // Inventory actions: the page posts approvals here (the service re-checks the role and every rule).
  // A benchmark dataset has other product ids than the live ERP: nothing may be approved against it.
  actions: dataset.readOnly ? null : {
    log: () => actionsCall("GET", "/actions/log?limit=200"),
    post: (path, body) => actionsCall("POST", path, body),
    proposals: () => actionsCall("GET", "/proposals?status=proposed&limit=100"),
    dismiss: (id) => actionsCall("POST", `/proposals/${id}/dismiss`, {}),
  },
  async get(url, signal, update) {
    const u = new URL(url, location.origin);
    if (u.pathname === "/api/meta") return meta(signal);
    if (u.pathname === "/api/inventory") return inventory(signal);
    // Cheap unfiltered probe (rollup-served): the total number of order lines changes when new orders land.
    if (u.pathname === "/api/orders-version") {
      const rows = await Promise.all(Object.values(CH).map((c) => run({ measures: [`${c}.lines`] }, signal)));
      return { version: rows.reduce((n, r, i) => n + num(r[0]?.[`${Object.values(CH)[i]}.lines`] || 0), 0) };
    }
    if (u.pathname === "/api/dashboard") {
      const f = Object.fromEntries(["fy", "channel", "group", "region", "category", "subcategory"].map((k) => [k, u.searchParams.get(k) || ""]));
      return dashboard(f, signal, update, u.searchParams.get("feed") === "0");
    }
    throw new Error(`unknown endpoint ${u.pathname}`);
  },
});
