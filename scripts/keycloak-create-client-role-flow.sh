#!/usr/bin/env bash
set -euo pipefail

COMPOSE_SERVICE="${COMPOSE_SERVICE:-keycloak}"
KC_SERVER_URL="${KC_SERVER_URL:-http://localhost:8080}"
BASE_FLOW="${BASE_FLOW:-browser}"
DENY_MESSAGE="${DENY_MESSAGE:-Access denied: missing required role}"
RECREATE="${RECREATE:-false}"
KC_OPTS="${KC_OPTS:--XX:UseSVE=0}"

: "${REALM:?REALM is required}"
: "${TARGET_CLIENT_ID:?TARGET_CLIENT_ID is required}"
: "${REQUIRED_ROLE:?REQUIRED_ROLE is required}"
: "${KEYCLOAK_ADMIN:?KEYCLOAK_ADMIN is required}"
: "${KEYCLOAK_ADMIN_PASSWORD:?KEYCLOAK_ADMIN_PASSWORD is required}"

FLOW_ALIAS="${FLOW_ALIAS:-${TARGET_CLIENT_ID}-role-gated-browser}"
DENY_SUBFLOW_ALIAS="${DENY_SUBFLOW_ALIAS:-${FLOW_ALIAS}-deny-missing-${TARGET_CLIENT_ID}-${REQUIRED_ROLE}}"

kc() {
  docker compose exec -T -e "KC_OPTS=${KC_OPTS}" "${COMPOSE_SERVICE}" /opt/keycloak/bin/kcadm.sh "$@"
}

json_new_name() {
  python3 -c 'import json, sys; print(json.dumps({"newName": sys.argv[1]}))' "$1"
}

url_encode() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

json_condition_config() {
  python3 -c '
import json
import sys

print(json.dumps({
    "alias": "User lacks required client role",
    "config": {
        "condUserRole": sys.argv[1],
        "negate": "true",
    },
}))
' "$1"
}

json_deny_config() {
  python3 -c '
import json
import sys

print(json.dumps({
    "alias": "Deny missing role",
    "config": {
        "denyErrorMessage": sys.argv[1],
    },
}))
' "$1"
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

forms_flow_alias_from_json() {
  python3 -c '
import json
import sys

flow_alias = sys.argv[1]
executions = json.load(sys.stdin)

for execution in executions:
    display = execution.get("displayName") or execution.get("alias") or execution.get("flowAlias") or ""
    if execution.get("authenticationFlow") and display.lower().endswith(" forms"):
        print(execution.get("flowAlias") or display)
        raise SystemExit

for execution in executions:
    display = execution.get("displayName") or execution.get("alias") or execution.get("flowAlias") or ""
    if execution.get("authenticationFlow") and "forms" in display.lower():
        print(execution.get("flowAlias") or display)
        raise SystemExit

print(f"{flow_alias} forms")
' "$1"
}

execution_id_from_json() {
  python3 -c '
import json
import sys

match = sys.argv[1]
for execution in json.load(sys.stdin):
    candidates = {
        execution.get("id"),
        execution.get("displayName"),
        execution.get("alias"),
        execution.get("flowAlias"),
        execution.get("providerId"),
    }
    if match in candidates:
        print(execution["id"])
        break
' "$1"
}

execution_id_by_provider_from_json() {
  python3 -c '
import json
import sys

provider_id = sys.argv[1]
for execution in reversed(json.load(sys.stdin)):
    if execution.get("providerId") == provider_id:
        print(execution["id"])
        break
' "$1"
}

set_execution_requirement() {
  local parent_flow_alias="$1"
  local execution_match="$2"
  local requirement="$3"
  local executions execution_id

  executions="$(kc get "authentication/flows/$(url_encode "${parent_flow_alias}")/executions" -r "${REALM}")"
  execution_id="$(printf '%s' "${executions}" | execution_id_from_json "${execution_match}")"

  if [[ -z "${execution_id}" ]]; then
    echo "Execution not found in flow ${parent_flow_alias}: ${execution_match}" >&2
    exit 1
  fi

  kc update "authentication/flows/$(url_encode "${parent_flow_alias}")/executions" \
    -r "${REALM}" \
    -n \
    -s "id=${execution_id}" \
    -s "requirement=${requirement}" >/dev/null
}

execution_id_by_provider() {
  local parent_flow_alias="$1"
  local provider_id="$2"
  local executions

  executions="$(kc get "authentication/flows/$(url_encode "${parent_flow_alias}")/executions" -r "${REALM}")"
  printf '%s' "${executions}" | execution_id_by_provider_from_json "${provider_id}"
}

kc config credentials \
  --server "${KC_SERVER_URL}" \
  --realm master \
  --user "${KEYCLOAK_ADMIN}" \
  --password "${KEYCLOAK_ADMIN_PASSWORD}" >/dev/null

client_json="$(kc get clients -r "${REALM}" -q "clientId=${TARGET_CLIENT_ID}" --fields id,clientId)"
client_uuid="$(printf '%s' "${client_json}" | client_id_from_json "${TARGET_CLIENT_ID}")"

if [[ -z "${client_uuid}" ]]; then
  echo "Client not found in realm ${REALM}: ${TARGET_CLIENT_ID}" >&2
  exit 1
fi

kc get "clients/${client_uuid}/roles/${REQUIRED_ROLE}" -r "${REALM}" >/dev/null

flows_json="$(kc get authentication/flows -r "${REALM}")"
existing_flow_id="$(printf '%s' "${flows_json}" | flow_id_from_json "${FLOW_ALIAS}")"

if [[ -n "${existing_flow_id}" && "${RECREATE}" == "true" ]]; then
  kc delete "authentication/flows/${existing_flow_id}" -r "${REALM}"
  existing_flow_id=""
fi

if [[ -z "${existing_flow_id}" ]]; then
  kc create "authentication/flows/$(url_encode "${BASE_FLOW}")/copy" \
    -r "${REALM}" \
    -b "$(json_new_name "${FLOW_ALIAS}")" >/dev/null

  top_executions="$(kc get "authentication/flows/$(url_encode "${FLOW_ALIAS}")/executions" -r "${REALM}")"
  forms_flow_alias="$(printf '%s' "${top_executions}" | forms_flow_alias_from_json "${FLOW_ALIAS}")"

  kc create "authentication/flows/$(url_encode "${forms_flow_alias}")/executions/flow" \
    -r "${REALM}" \
    -s "alias=${DENY_SUBFLOW_ALIAS}" \
    -s type=basic-flow \
    -s provider=basic-flow \
    -s "description=Reject users missing ${TARGET_CLIENT_ID}.${REQUIRED_ROLE}" >/dev/null
  set_execution_requirement "${forms_flow_alias}" "${DENY_SUBFLOW_ALIAS}" CONDITIONAL

  kc create "authentication/flows/$(url_encode "${DENY_SUBFLOW_ALIAS}")/executions/execution" \
    -r "${REALM}" \
    -s provider=conditional-user-role >/dev/null
  condition_execution_id="$(execution_id_by_provider "${DENY_SUBFLOW_ALIAS}" conditional-user-role)"
  set_execution_requirement "${DENY_SUBFLOW_ALIAS}" "${condition_execution_id}" REQUIRED
  kc create "authentication/executions/${condition_execution_id}/config" \
    -r "${REALM}" \
    -b "$(json_condition_config "${TARGET_CLIENT_ID}.${REQUIRED_ROLE}")" >/dev/null

  kc create "authentication/flows/$(url_encode "${DENY_SUBFLOW_ALIAS}")/executions/execution" \
    -r "${REALM}" \
    -s provider=deny-access-authenticator >/dev/null
  deny_execution_id="$(execution_id_by_provider "${DENY_SUBFLOW_ALIAS}" deny-access-authenticator)"
  set_execution_requirement "${DENY_SUBFLOW_ALIAS}" "${deny_execution_id}" REQUIRED
  kc create "authentication/executions/${deny_execution_id}/config" \
    -r "${REALM}" \
    -b "$(json_deny_config "${DENY_MESSAGE}")" >/dev/null
fi

flows_json="$(kc get authentication/flows -r "${REALM}")"
flow_id="$(printf '%s' "${flows_json}" | flow_id_from_json "${FLOW_ALIAS}")"

echo "Created or reused flow:"
echo "  realm: ${REALM}"
echo "  flow alias: ${FLOW_ALIAS}"
echo "  flow id: ${flow_id}"
echo
echo "Activation command for client ${TARGET_CLIENT_ID}:"
echo "  kcadm.sh update clients/${client_uuid} -r ${REALM} -s authenticationFlowBindingOverrides.browser=${flow_id}"
