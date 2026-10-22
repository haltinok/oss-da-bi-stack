// Data source for the existing dashboard: signs in through Keycloak (authorization code + PKCE),
// swaps the Keycloak token for a 15-minute Cube token, and answers the page's two calls,
// /api/meta and /api/dashboard, with Cube queries (via @cubejs-client/core) instead of SQL.
// The shapes returned are exactly those of dashboard/app.py, so app.js is unchanged apart
// from a one-line hook in getJSON() and null-safe handling of hidden profit figures.
import cubejs from "./vendor/cubejs-client-core.mjs";

const C = window.SPIKE;
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
// Orders: `orders_placed` (each order once, on its first line) is exact for any grouping or filter on
// order-level attributes and is additive, so a plain rollup serves it even under a multi-region
// security filter. It is wrong as soon as products are involved (an order has several categories),
// so product filters switch to the exact distinct count, which only a direct scan can answer.
const ordersOf = (f) => (f && (f.category || f.subcategory) ? "orders" : "orders_placed");
const measures = (ch, f, orders = ordersOf(f)) => [
  `${CH[ch]}.revenue`, ...(profit() ? [`${CH[ch]}.gross_profit`] : []), `${CH[ch]}.${orders}`, `${CH[ch]}.units`,
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

async function dashboard(f, signal) {
  const chans = channels(f);
  const perChannel = (fn) => Promise.all(chans.map((ch) => fn(ch).then((rows) => ({ ch, rows }))));

  const kpiQ = perChannel((ch) => run({
    measures: measures(ch, f),
    dimensions: f.fy ? ["dates.fiscal_year"] : [],
    filters: [...filters(f, ["fy"]),
      ...(f.fy ? [{ member: "dates.fiscal_year", operator: "equals", values: [String(f.fy), String(f.fy - 1)] }] : [])],
  }, signal));
  const monthlyQ = perChannel((ch) => run({
    measures: measures(ch, f), filters: filters(f),
    timeDimensions: [{ dimension: `${CH[ch]}.order_date`, granularity: "month" }],
    order: { [`${CH[ch]}.order_date`]: "asc" },
  }, signal));
  // Orders per category = distinct orders containing it (not additive): a rollup answers that for admins
  // and single-territory users only; for a multi-territory user the column is left empty rather than slow.
  const exactMix = session.role === "admin" || (session.territories || []).length === 1;
  const mixQ = perChannel((ch) => run({
    measures: exactMix ? measures(ch, f, "orders") : measures(ch, f, "orders").filter((m) => !m.endsWith(".orders")),
    dimensions: ["products.category", "products.subcategory"],
    filters: filters(f, ["category", "subcategory"]),
  }, signal));
  const productsQ = perChannel((ch) => run({
    measures: [`${CH[ch]}.revenue`, ...(profit() ? [`${CH[ch]}.gross_profit`] : []), `${CH[ch]}.units`],
    dimensions: ["products.name", "products.category"], filters: filters(f),
  }, signal));
  const territoriesQ = perChannel((ch) => run({
    measures: [`${CH[ch]}.revenue`, ...(profit() ? [`${CH[ch]}.gross_profit`] : []), `${CH[ch]}.${ordersOf(f)}`],
    dimensions: ["territories.group_name", "territories.region"], filters: filters(f, ["group", "region"]),
  }, signal));
  // Newest orders ignore the fiscal-year filter. Find the newest day from the daily rollup, then
  // read only the last week (one or two month partitions) instead of aggregating every order.
  const latestQ = perChannel(async (ch) => {
    const c = CH[ch];
    const last = await run({ measures: [`${c}.revenue`], filters: filters(f, ["fy"]),
      timeDimensions: [{ dimension: `${c}.order_date`, granularity: "day" }],
      order: { [`${c}.order_date`]: "desc" }, limit: 1 }, signal);
    if (!last.length) return [];
    const end = day(last[0][`${c}.order_date.day`]);
    return run({
      measures: [`${c}.lines`, `${c}.revenue`],
      dimensions: [`${c}.order_number`, `${c}.order_date`, "territories.region", `${c}.order_status`],
      filters: filters(f, ["fy"]),
      timeDimensions: [{ dimension: `${c}.order_date`, dateRange: [addDays(end, -6), end] }],
      order: { [`${c}.order_date`]: "desc", [`${c}.order_number`]: "desc" }, limit: 8,
    }, signal);
  });

  const [kpi, monthly, mix, products, territories, latest] =
    await Promise.all([kpiQ, monthlyQ, mixQ, productsQ, territoriesQ, latestQ]);

  // KPIs: current (the picked fiscal year, or everything) vs previous year.
  let current = null, previous = null;
  for (const { ch, rows } of kpi) {
    for (const r of rows) {
      const fig = figures(ch, r);
      const isPrev = f.fy && Number(r["dates.fiscal_year"]) === Number(f.fy) - 1;
      if (isPrev) previous = add(previous || ZERO, fig); else current = add(current || ZERO, fig);
    }
  }
  const monthlyRows = monthly.flatMap(({ ch, rows }) => rows.map((r) => ({
    month: day(r[`${CH[ch]}.order_date.month`]), channel: ch, ...figures(ch, r),
  }))).sort((a, b) => (a.month < b.month ? -1 : a.month > b.month ? 1 : a.channel < b.channel ? -1 : 1));

  const mixMap = new Map();
  for (const { ch, rows } of mix) {
    for (const r of rows) {
      const key = `${r["products.category"]}\u0000${r["products.subcategory"]}`;
      const cur = mixMap.get(key) || { category: r["products.category"], subcategory: r["products.subcategory"], ...ZERO };
      mixMap.set(key, { ...cur, ...add(cur, figures(ch, r)) });
    }
  }
  const mixRows = [...mixMap.values()].sort((a, b) => b.revenue - a.revenue);

  const prodMap = new Map();
  for (const { ch, rows } of products) {
    for (const r of rows) {
      const name = r["products.name"];
      const cur = prodMap.get(name) || { product_name: name, category: r["products.category"], revenue: 0, internet: 0, reseller: 0, gross_profit: 0, units: 0 };
      const rev = num(r[`${CH[ch]}.revenue`]);
      const gp = profit() ? num(r[`${CH[ch]}.gross_profit`]) : null;
      prodMap.set(name, {
        ...cur, revenue: cur.revenue + rev, [ch.toLowerCase()]: cur[ch.toLowerCase()] + rev,
        gross_profit: gp == null || cur.gross_profit == null ? null : cur.gross_profit + gp,
        units: cur.units + num(r[`${CH[ch]}.units`]),
      });
    }
  }
  const topProducts = [...prodMap.values()].sort((a, b) => b.revenue - a.revenue).slice(0, 10);

  const terrMap = new Map();
  for (const { ch, rows } of territories) {
    for (const r of rows) {
      const key = r["territories.region"];
      const cur = terrMap.get(key) || { grp: r["territories.group_name"], region: key, revenue: 0, internet: 0, reseller: 0, gross_profit: 0, orders: 0 };
      const rev = num(r[`${CH[ch]}.revenue`]);
      const gp = profit() ? num(r[`${CH[ch]}.gross_profit`]) : null;
      terrMap.set(key, {
        ...cur, revenue: cur.revenue + rev, [ch.toLowerCase()]: cur[ch.toLowerCase()] + rev,
        gross_profit: gp == null || cur.gross_profit == null ? null : cur.gross_profit + gp,
        orders: cur.orders + num(r[`${CH[ch]}.orders`] ?? r[`${CH[ch]}.orders_placed`]),
      });
    }
  }
  const territoryRows = [...terrMap.values()].sort((a, b) => b.revenue - a.revenue);

  const latestOrders = latest.flatMap(({ ch, rows }) => rows.map((r) => ({
    sales_order_number: r[`${CH[ch]}.order_number`], channel: ch,
    order_date: r[`${CH[ch]}.order_date`].replace(/\.\d+$/, ""), region: r["territories.region"],
    order_status: num(r[`${CH[ch]}.order_status`]), lines: num(r[`${CH[ch]}.lines`]), revenue: num(r[`${CH[ch]}.revenue`]),
  }))).sort((a, b) => (a.order_date === b.order_date ? (a.sales_order_number < b.sales_order_number ? 1 : -1) : a.order_date < b.order_date ? 1 : -1)).slice(0, 8);

  return {
    kpis: { current, previous }, monthly: monthlyRows, mix: mixRows, top_products: topProducts,
    territories: territoryRows, latest_orders: latestOrders, generated_at: new Date().toISOString(),
  };
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
  async get(url, signal) {
    const u = new URL(url, location.origin);
    if (u.pathname === "/api/meta") return meta(signal);
    if (u.pathname === "/api/dashboard") {
      const f = Object.fromEntries(["fy", "channel", "group", "region", "category", "subcategory"].map((k) => [k, u.searchParams.get(k) || ""]));
      return dashboard(f, signal);
    }
    throw new Error(`unknown endpoint ${u.pathname}`);
  },
});
