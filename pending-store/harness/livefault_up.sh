#!/usr/bin/env bash
# Bring up the Base Sepolia stack with the fault proxy for one facilitator image and wait until
# it answers. The settlements are real Base Sepolia transactions: the signer pays the gas in
# Base Sepolia ETH and the buyer pays in Circle's test USDC.
#   ./livefault_up.sh <variant> <facilitator image>   prints the run directory (logs/live/...)
# Needs XD_FACILITATOR_SIGNER (hex private key of a signer holding Base Sepolia ETH) and XD_PAY_TO
# (the seller's address) in the environment. Stop it with ./livefault_down.sh <run dir>.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VARIANT="${1:?variant}"; IMAGE="${2:?image}"
: "${XD_FACILITATOR_SIGNER:?}" "${XD_PAY_TO:?}"
export RUN_DIR="$HERE/../logs/live/fault-$VARIANT-$(date -u +%Y%m%dT%H%M%SZ)"
export FACILITATOR_IMAGE="$IMAGE" HOST_UID_GID="$(id -u):$(id -g)"
PROJECT="x402-pending-live-$(printf %s "$VARIANT" | tr -c "a-z0-9_-" "-")"
mkdir -p "$RUN_DIR"; echo "$PROJECT" > "$RUN_DIR/project.txt"
{ echo "variant: $VARIANT"; echo "image: $IMAGE"; docker image inspect "$IMAGE" --format 'image id: {{.Id}}{{"\n"}}labels: {{json .Config.Labels}}'; } > "$RUN_DIR/image.txt"
docker compose -p "$PROJECT" -f "$HERE/docker-compose.livefault.yml" up -d --quiet-pull > "$RUN_DIR/compose-up.log" 2>&1
for i in $(seq 1 60); do
  if curl -sf -m 3 http://127.0.0.1:19462/supported > "$RUN_DIR/supported.json" 2>/dev/null && curl -sf -m 3 http://127.0.0.1:19463/healthz > /dev/null 2>&1; then
    echo "$RUN_DIR"; exit 0
  fi
  sleep 2
done
echo "stack did not come up; see $RUN_DIR" >&2; exit 1
