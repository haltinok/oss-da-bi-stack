// The Cube client every dashboard page shares: Keycloak sign-in (authorization code + PKCE), the 15-minute Cube token from the
// auth service, and a query runner. Row-level security lives in Cube (cube/cube.js) and the token carries the user's role and
// territories; nothing here can widen what a user sees.
//
//   const client = createCubeClient({ stack: window.STACK, apiUrl: dataset.cube, onSession: (s) => ... });
//   await client.token();                          // signs in (redirecting if needed)
//   const rows = await client.run({ measures: ["internet_sales.revenue"] }, signal);
import cubejs from "./vendor/cubejs-client-core.mjs";

const store = {
  get: (k) => { try { return JSON.parse(sessionStorage.getItem(k)); } catch { return null; } },
  set: (k, v) => { try { sessionStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  del: (k) => { try { sessionStorage.removeItem(k); } catch { /* ignore */ } },
};
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

/**
 * @param stack      window.STACK: { keycloak: { url, realm, clientId }, auth, ... }
 * @param apiUrl     the Cube endpoint to query (a dataset's `cube`)
 * @param redirect   where Keycloak sends the browser back to; must be a redirect URI of the Keycloak client (default: the site root)
 * @param onSession  called with { token, expires, user, role, territories } each time a new Cube token is minted
 */
export function createCubeClient({ stack, apiUrl, redirect = `${location.origin}/`, onSession = () => {} }) {
  const KC = `${stack.keycloak.url}/realms/${stack.keycloak.realm}/protocol/openid-connect`;
  const clientId = stack.keycloak.clientId;

  async function login() {
    const verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
    const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
    const state = b64url(crypto.getRandomValues(new Uint8Array(16)));
    store.set("pkce", { verifier, state });
    const p = new URLSearchParams({
      client_id: clientId, redirect_uri: redirect, response_type: "code", scope: "openid",
      code_challenge: challenge, code_challenge_method: "S256", state,
    });
    location.assign(`${KC}/auth?${p}`);
    return new Promise(() => {}); // never resolves: the page navigates away
  }

  async function tokenRequest(params) {
    const res = await fetch(`${KC}/token`, {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ client_id: clientId, ...params }),
    });
    if (!res.ok) throw new Error(`Keycloak token request failed (${res.status})`);
    const t = await res.json();
    const tokens = { access: t.access_token, refresh: t.refresh_token, expires: Date.now() + t.expires_in * 1000 };
    store.set("kc", tokens);
    return tokens;
  }

  /** The Keycloak tokens: finishes a sign-in in progress, refreshes an expiring token, or starts a sign-in. */
  async function keycloak() {
    const code = new URLSearchParams(location.search).get("code");
    if (code) {
      const { verifier, state } = store.get("pkce") || {};
      const back = new URLSearchParams(location.search).get("state");
      history.replaceState({}, "", redirect); // drop ?code=... from the address bar
      store.del("pkce");
      if (!verifier || back !== state) return login();
      return tokenRequest({ grant_type: "authorization_code", code, redirect_uri: redirect, code_verifier: verifier });
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

  let session = null; // { token, expires, user, role, territories }

  /** The Cube token (a short-lived JWT from the auth service), minted again when it is about to expire. */
  async function token(force = false) {
    if (!force && session && session.expires - Date.now() > 60_000) return session.token;
    const kc = await keycloak();
    const res = await fetch(`${stack.auth}/token`, { method: "POST", headers: { Authorization: `Bearer ${kc.access}` } });
    if (res.status === 401) { store.del("kc"); return login(); }
    if (!res.ok) throw new Error(res.status === 403 ? "Your account has no access to this dashboard" : `Sign-in failed (${res.status})`);
    const t = await res.json();
    session = { token: t.token, expires: Date.now() + t.expires_in * 1000, user: t.user, role: t.role, territories: t.territories };
    onSession(session);
    return session.token;
  }

  const api = cubejs(() => token(), { apiUrl });

  /** Run one Cube query and return its rows; a rejected token is renewed once. */
  async function run(query, signal) {
    try {
      return (await api.load(query, { signal })).rawData();
    } catch (e) {
      if (e?.status === 401) { await token(true); return (await api.load(query, { signal })).rawData(); }
      throw e;
    }
  }

  /** Forget the Keycloak token (a service answered 401): the next call signs in again. */
  const dropKeycloakToken = () => store.del("kc");

  /** End the Keycloak session and come back to the sign-in page. */
  function signOut() {
    store.del("kc");
    location.assign(`${KC}/logout?${new URLSearchParams({ client_id: clientId, post_logout_redirect_uri: redirect })}`);
  }

  return { token, run, keycloak, dropKeycloakToken, signOut, session: () => session };
}
