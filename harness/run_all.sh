#!/usr/bin/env bash
# Run the #136 harness against one facilitator image: bring up the Celo fork, the fault proxy and
# the facilitator (compose project w3-x402-<variant>), settle every scenario, keep the logs,
# then remove the containers, network and volumes.
#   ./run_all.sh <variant> <image> [scenarios] [reps]
# Needs: docker compose, and a Python with eth-account and httpx (PYTHON, default python3).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VARIANT="${1:?variant}"; IMAGE="${2:?image}"; SCENARIOS="${3:-}"; REPS="${4:-0}"
PYTHON="${PYTHON:-python3}"
export RUN_DIR="$HERE/../logs/run-$VARIANT-$(date -u +%Y%m%dT%H%M%SZ)"
export FACILITATOR_IMAGE="$IMAGE" HOST_UID_GID="$(id -u):$(id -g)"
PROJECT="w3-x402-$(printf %s "$VARIANT" | tr -c "a-z0-9_-" "-")"
mkdir -p "$RUN_DIR"
compose() { docker compose -p "$PROJECT" -f "$HERE/docker-compose.yml" "$@"; }
cleanup() {
  compose logs --no-color --timestamps facilitator > "$RUN_DIR/facilitator.log" 2>&1 || true
  compose logs --no-color --timestamps anvil > "$RUN_DIR/anvil.log" 2>&1 || true
  compose down -v --remove-orphans > /dev/null 2>&1 || true
}
trap cleanup EXIT
{
  echo "variant: $VARIANT"
  echo "image: $IMAGE"
  docker image inspect "$IMAGE" --format 'image id: {{.Id}}{{"\n"}}labels: {{json .Config.Labels}}'
} > "$RUN_DIR/image.txt"
compose up -d --quiet-pull > "$RUN_DIR/compose-up.log" 2>&1
ARGS=(--label "$VARIANT" --out "$RUN_DIR")
[ -n "$SCENARIOS" ] && ARGS+=(--scenarios "$SCENARIOS")
[ "$REPS" != "0" ] && ARGS+=(--reps "$REPS")
"$PYTHON" "$HERE/run_settles.py" "${ARGS[@]}"
echo "logs: $RUN_DIR"
