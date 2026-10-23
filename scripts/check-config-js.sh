#!/usr/bin/env bash
# Render dashboard/cube/nginx.conf.template the way the nginx image does (envsubst) for several settings and evaluate the
# /cube/config.js it serves, so the browser configuration cannot drift from what the dashboard expects:
# local ports vs path routing (PUBLIC_URL), and the dataset (live | 250m). Needs docker and node.
set -euo pipefail
cd "$(dirname "$0")/.."
render() {  # env assignments as arguments; prints the JS of config.js
  docker run --rm "${@/#/-e}" -e KEYCLOAK_PORT=8180 -e AUTH_PORT=8200 -e CUBE_PORT=4000 -e ACTIONS_PORT=8300 \
    -v "$PWD/dashboard/cube/nginx.conf.template:/etc/nginx/templates/default.conf.template:ro" nginx:1.27-alpine \
    sh -c '/docker-entrypoint.d/20-envsubst-on-templates.sh >/dev/null 2>&1; nginx -t >/dev/null 2>&1 || { echo "nginx -t failed" >&2; exit 1; }; grep "return 200" /etc/nginx/conf.d/default.conf' \
    | sed -E "s/^ *return 200 '//; s/';\$//"
}
check() {  # name, js, assertions (node expression over STACK)
  node -e "const window = {}; eval(process.argv[1]); const S = window.STACK; const ok = ($3); if (!ok) { console.error('FAIL $1', JSON.stringify(S)); process.exit(1); } console.log('ok   $1')" "$2"
}
js=$(render PUBLIC_URL=http://localhost:8250 PATH_ROUTING= DATASET=live CUBE_250M_PORT=)
check "local, live" "$js" 'S.keycloak.url === "http://localhost:8180" && S.cube === "http://localhost:4000/cubejs-api/v1" && S.datasets.length === 1 && S.datasets[0].id === "live" && S.datasets[0].mart === "mart" && !S.datasets[0].readOnly'
js=$(render PUBLIC_URL=http://localhost:8250 PATH_ROUTING= DATASET=250m CUBE_250M_PORT=)
check "local, 250m" "$js" 'S.datasets.length === 1 && S.datasets[0].id === "250m" && S.datasets[0].mart === "mart_250m" && S.datasets[0].readOnly === true && S.datasets[0].label === "250M benchmark" && S.datasets[0].cube === S.cube'
js=$(render PUBLIC_URL=https://demo.example.test PATH_ROUTING=1 DATASET=250m CUBE_250M_PORT=)
check "public, 250m" "$js" 'S.keycloak.url === "https://demo.example.test/kc" && S.cube === "https://demo.example.test/cubejs-api/v1" && S.datasets[0].mart === "mart_250m" && S.datasets[0].readOnly === true'
js=$(render PUBLIC_URL=http://localhost:8250 PATH_ROUTING= DATASET=live CUBE_250M_PORT=4001)
check "local, live + the second Cube (switch)" "$js" 'S.datasets.length === 2 && S.datasets[1].id === "250m" && S.datasets[1].readOnly === true'
js=$(render PUBLIC_URL=http://localhost:8250 PATH_ROUTING= DATASET=250m CUBE_250M_PORT=4001)
check "250m deployment ignores the second Cube" "$js" 'S.datasets.length === 1'
