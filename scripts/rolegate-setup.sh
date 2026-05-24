#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export ROLEGATE_PROG="${0##*/}"
exec python3 "${SCRIPT_DIR}/rolegate_setup.py" "$@"
