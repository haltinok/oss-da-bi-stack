// Data source for the existing dashboard: signs in through Keycloak (authorization code + PKCE),
// swaps the Keycloak token for a 15-minute Cube token, and answers the page's two calls,
// /api/meta and /api/dashboard, with Cube queries (via @cubejs-client/core) instead of SQL.
// The shapes returned are exactly those of the former Postgres-backed dashboard/app.py, so app.js is unchanged apart
// from a one-line hook in getJSON() and null-safe handling of hidden profit figures.
import cubejs from "./vendor/cubejs-client-core.mjs";

const C = window.STACK;
const KC = `${C.keycloak.url}/realms/${C.keycloak.realm}/protocol/openid-connect`;
const REDIRECT = `${location.origin}/`;
const store = {
  get: (k) => { try { return JSON.parse(sessionStorage.getItem(k)); } catch { return null; } },
  set: (k, v) => { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  del: (k) => { try { sessionStorage.removeItem(k); } catch { /* ignore */ } },
};

// ------------------------------------------------------------------ Keycloak sign-in (PKCE)
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function login() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const state = b64url(crypto.getRandomValues(new Uint8Array(16)));
  store.set("pkce", { verifier, state });
  const p = new URLSearchParams({
    client_id: C.keycloak.clientId, redirect_uri: REDIRECT, response_type: "code", scope: "openid",
    code_challenge: challenge, code_challenge_method: "S256", state,
  });
  location.assign(`${KC}/auth?${p}`);
  return new Promise(() => {}); // never resolves: the page navigates away
}

async function tokenRequest(params) {
  const res = await fetch(`${KC}/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: C.keycloak.clientId, ...params }),
  });
  if (!res.ok) throw new Error(`Keycloak token request failed (${res.status})`);
  const t = await res.json();
  const tokens = { access: t.access_token, refresh: t.refresh_token, expires: Date.now() + t.expires_in * 1000 };
  store.set("kc", tokens);
  return tokens;
}

async function keycloakTokens() {
  const code = new URLSearchParams(location.search).get("code");
  if (code) {
    const { verifier, state } = store.get("pkce") || {};
    const back = new URLSearchParams(location.search).get("state");
    history.replaceState({}, "", REDIRECT); // drop ?code=... from the address bar
    store.del("pkce");
    if (!verifier || back !== state) return login();
    return tokenRequest({ grant_type: "authorization_code", code, redirect_uri: REDIRECT, code_verifier: verifier });
  }
  const t = store.get("kc");
  if (!t) return login();
  if (t.expires - Date.now() > 30_000) return t;
  try {
    return await tokenRequest({ grant_type: "refresh_token", refresh_token: t.refresh });
  } catch {
    store.del("kc");
    return login();
  }
}

// ------------------------------------------------------------------ Cube token (via auth service)
let session = null; // { token, expires, user, role }

async function cubeToken(force = false) {
  if (!force && session && session.expires - Date.now() > 60_000) return session.token;
  const kc = await keycloakTokens();
  const res = await fetch(`${C.auth}/token`, { method: "POST", headers: { Authorization: `Bearer ${kc.access}` } });
  if (res.status === 401) { store.del("kc"); return login(); }
  if (!res.ok) throw new Error(res.status === 403 ? "Your account has no access to this dashboard" : `Sign-in failed (${res.status})`);
  const t = await res.json();
  session = { token: t.token, expires: Date.now() + t.expires_in * 1000, user: t.user, role: t.role, territories: t.territories };
  window.dashboardData.noProfit = t.role === "rep"; // profit/margin are not available to reps
  showWho();
  return session.token;
}

function showWho() {
  if (document.getElementById("who")) return;
  const who = document.createElement("div");
  who.id = "who";
  who.style.cssText = "margin-left:auto;font-size:12px;opacity:.8;white-space:nowrap";
  who.innerHTML = `${session.user} (${session.role}) · <a href="#" id="signout">Sign out</a>`;
  document.querySelector("header.top")?.append(who);
  document.getElementById("signout").addEventListener("click", (e) => {
    e.preventDefault();
    store.del("kc");
    location.assign(`${KC}/logout?${new URLSearchParams({ client_id: C.keycloak.clientId, post_logout_redirect_uri: REDIRECT })}`);
  });
}

// ------------------------------------------------------------------ Cube queries
const api = cubejs(() => cubeToken(), { apiUrl: C.cube });
const CH = { Internet: "internet_sales", Reseller: "reseller_sales" };
const num = (v) => (v == null ? null : Number(v));

async function run(query, signal) {
  try {
    return (await api.load(query, { signal })).rawData();
  } catch (e) {
    if (e?.status === 401) { await cubeToken(true); return (await api.load(query, { signal })).rawData(); }
    throw e;
  }
}

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

// ------------------------------------------------------------------ the two endpoints the page calls
await cubeToken(); // signs in (redirecting if needed) before the first request
window.__dashboardDataReady({
  async get(url, signal, update) {
    const u = new URL(url, location.origin);
    if (u.pathname === "/api/meta") return meta(signal);
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
