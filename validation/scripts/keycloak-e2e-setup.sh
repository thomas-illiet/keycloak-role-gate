#!/usr/bin/env bash
set -euo pipefail

COMPOSE_SERVICE="${COMPOSE_SERVICE:-keycloak}"
KC_SERVER_URL="${KC_SERVER_URL:-http://localhost:8080}"
REALM="${REALM:-role-gate-e2e}"
TARGET_CLIENT_ID="${TARGET_CLIENT_ID:-python-app}"
REQUIRED_ROLE="${REQUIRED_ROLE:-app-access}"
OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-python-app-secret}"
APP_BASE_URL="${APP_BASE_URL:-http://localhost:8000}"
FLOW_ALIAS="${FLOW_ALIAS:-${TARGET_CLIENT_ID}-role-gated-browser}"
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
E2E_USER_PASSWORD="${E2E_USER_PASSWORD:-password}"
RESET_E2E_REALM="${RESET_E2E_REALM:-true}"
KC_OPTS="${KC_OPTS:--XX:UseSVE=0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_ROOT}/validation/docker-compose.yml}"

export COMPOSE_FILE REALM TARGET_CLIENT_ID REQUIRED_ROLE FLOW_ALIAS KEYCLOAK_ADMIN KEYCLOAK_ADMIN_PASSWORD

kc() {
  docker compose exec -T -e "KC_OPTS=${KC_OPTS}" "${COMPOSE_SERVICE}" /opt/keycloak/bin/kcadm.sh "$@"
}

client_json_body() {
  python3 -c '
import json
import sys

client_id, secret, app_base_url = sys.argv[1:4]
print(json.dumps({
    "clientId": client_id,
    "enabled": True,
    "protocol": "openid-connect",
    "publicClient": False,
    "clientAuthenticatorType": "client-secret",
    "secret": secret,
    "standardFlowEnabled": True,
    "directAccessGrantsEnabled": False,
    "serviceAccountsEnabled": False,
    "redirectUris": [f"{app_base_url}/auth/callback"],
    "webOrigins": [app_base_url],
    "attributes": {
        "post.logout.redirect.uris": app_base_url,
    },
}))
' "$1" "$2" "$3"
}

client_id_from_json() {
  python3 -c '
import json
import sys

target = sys.argv[1]
for client in json.load(sys.stdin):
    if client.get("clientId") == target:
        print(client["id"])
        break
' "$1"
}

first_user_id_from_json() {
  python3 -c '
import json
import sys

users = json.load(sys.stdin)
print(users[0]["id"])
'
}

flow_id_from_json() {
  python3 -c '
import json
import sys

target = sys.argv[1]
for flow in json.load(sys.stdin):
    if flow.get("alias") == target:
        print(flow["id"])
        break
' "$1"
}

echo "Waiting for Keycloak admin API..."
for _ in $(seq 1 60); do
  if kc config credentials \
    --server "${KC_SERVER_URL}" \
    --realm master \
    --user "${KEYCLOAK_ADMIN}" \
    --password "${KEYCLOAK_ADMIN_PASSWORD}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

kc config credentials \
  --server "${KC_SERVER_URL}" \
  --realm master \
  --user "${KEYCLOAK_ADMIN}" \
  --password "${KEYCLOAK_ADMIN_PASSWORD}" >/dev/null

if kc get "realms/${REALM}" >/dev/null 2>&1; then
  if [[ "${RESET_E2E_REALM}" == "true" ]]; then
    echo "Deleting existing E2E realm ${REALM}..."
    kc delete "realms/${REALM}"
  else
    echo "Realm ${REALM} already exists and RESET_E2E_REALM=false; leaving it in place."
  fi
fi

if ! kc get "realms/${REALM}" >/dev/null 2>&1; then
  echo "Creating realm ${REALM}..."
  kc create realms \
    -s "realm=${REALM}" \
    -s enabled=true \
    -s registrationAllowed=false \
    -s sslRequired=none >/dev/null
fi

echo "Creating OIDC client ${TARGET_CLIENT_ID}..."
kc create clients \
  -r "${REALM}" \
  -b "$(client_json_body "${TARGET_CLIENT_ID}" "${OIDC_CLIENT_SECRET}" "${APP_BASE_URL}")" >/dev/null

client_uuid="$(
  kc get clients -r "${REALM}" -q "clientId=${TARGET_CLIENT_ID}" --fields id,clientId |
    client_id_from_json "${TARGET_CLIENT_ID}"
)"

echo "Creating required client role ${REQUIRED_ROLE}..."
kc create "clients/${client_uuid}/roles" \
  -r "${REALM}" \
  -s "name=${REQUIRED_ROLE}" \
  -s "description=Required to access the Python E2E target" >/dev/null

create_user() {
  local username="$1"
  local first_name="$2"
  local last_name="$3"

  kc create users \
    -r "${REALM}" \
    -s "username=${username}" \
    -s "email=${username}@example.test" \
    -s enabled=true \
    -s emailVerified=true \
    -s "firstName=${first_name}" \
    -s "lastName=${last_name}" >/dev/null
  kc set-password \
    -r "${REALM}" \
    --username "${username}" \
    --new-password "${E2E_USER_PASSWORD}" >/dev/null
}

echo "Creating test users..."
create_user allowed Allowed User
create_user blocked Blocked User

allowed_user_id="$(
  kc get users -r "${REALM}" -q username=allowed --fields id,username |
    first_user_id_from_json
)"

role_json="$(kc get "clients/${client_uuid}/roles/${REQUIRED_ROLE}" -r "${REALM}")"
echo "Assigning ${TARGET_CLIENT_ID}.${REQUIRED_ROLE} to allowed..."
printf '[%s]' "${role_json}" |
  kc create "users/${allowed_user_id}/role-mappings/clients/${client_uuid}" \
    -r "${REALM}" \
    -f - >/dev/null

echo "Creating role-gated browser flow..."
RECREATE=true "${REPO_ROOT}/scripts/keycloak-create-client-role-flow.sh"

flow_id="$(kc get authentication/flows -r "${REALM}" | flow_id_from_json "${FLOW_ALIAS}")"

echo "Activating flow ${FLOW_ALIAS} on client ${TARGET_CLIENT_ID}..."
kc update "clients/${client_uuid}" \
  -r "${REALM}" \
  -s "authenticationFlowBindingOverrides.browser=${flow_id}" >/dev/null

echo "E2E setup complete."
