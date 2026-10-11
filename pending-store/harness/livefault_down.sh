#!/usr/bin/env bash
# Save the facilitator and server logs of a live run, then remove its containers and network.
#   ./livefault_down.sh <run dir>
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$(cd "${1:?run dir}" && pwd)"; PROJECT="$(cat "$RUN_DIR/project.txt")"
export RUN_DIR FACILITATOR_IMAGE=unused XD_PAY_TO=unused XD_FACILITATOR_SIGNER=unused HOST_UID_GID="$(id -u):$(id -g)"
c() { docker compose -p "$PROJECT" -f "$HERE/docker-compose.livefault.yml" "$@"; }
c logs --no-color --timestamps facilitator > "$RUN_DIR/facilitator.log" 2>&1
c logs --no-color --timestamps server > "$RUN_DIR/server.console.log" 2>&1
c down -v --remove-orphans > /dev/null 2>&1
echo "down: $PROJECT; logs in $RUN_DIR"
