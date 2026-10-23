# Shared by keycloak/sync-users.sh and keycloak/update-public-url.sh (source it after loading .env).
#
# Behind Caddy (docker-compose.public.yml) Keycloak serves under /kc; a local run serves at the root. The two modes
# are told apart the way the rest of the stack does: a PUBLIC_URL that is not http://localhost... is a public deployment.
public_url() { echo "${PUBLIC_URL:-http://localhost:${DASHBOARD_CUBE_PORT:-8250}}"; }
is_public() { case "$(public_url)" in http://localhost*|http://127.0.0.1*) return 1 ;; *) return 0 ;; esac; }
kc_server() { if is_public; then echo "http://localhost:8080/kc"; else echo "http://localhost:8080"; fi; }
kc() { docker compose --profile starrocks exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@"; }
kc_login() {
  kc config credentials --server "$(kc_server)" --realm master \
    --user "${KEYCLOAK_ADMIN:-admin}" --password "${KEYCLOAK_ADMIN_PASSWORD:?set KEYCLOAK_ADMIN_PASSWORD in .env}" >/dev/null
}
