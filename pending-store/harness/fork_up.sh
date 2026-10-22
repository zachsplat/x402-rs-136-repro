#!/usr/bin/env bash
# Bring up the Base Sepolia fork stack for one facilitator image, fund the facilitator signer
# (ETH) and the buyer (USDC) on the fork, and wait until every service answers.
#   ./fork_up.sh <variant> <facilitator image>     prints the run directory (logs/fork/...)
# Needs XD_FACILITATOR_SIGNER and XD_BUYER_PRIVATE_KEY (hex private keys) and XD_PAY_TO (the
# seller's address) in the environment. FACILITATOR_CONFIG picks a file in config/ (default
# facilitator-fork.json). PYTHON is an interpreter with httpx and eth-account. COMPOSE_OVERRIDE
# names a second compose file in this directory to add (docker-compose.restart.yml for the
# restart rows).
# Stop it with ./fork_down.sh <run dir> (keeps the logs, removes containers, network, volumes).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VARIANT="${1:?variant}"; IMAGE="${2:?image}"
: "${XD_FACILITATOR_SIGNER:?}" "${XD_BUYER_PRIVATE_KEY:?}" "${XD_PAY_TO:?}"
export RUN_DIR="$HERE/../logs/fork/fork-$VARIANT-$(date -u +%Y%m%dT%H%M%SZ)"
export FACILITATOR_IMAGE="$IMAGE" HOST_UID_GID="$(id -u):$(id -g)"
PROJECT="x402-pending-fork-$(printf %s "$VARIANT" | tr -c "a-z0-9_-" "-")"
export XD_PROJECT="$PROJECT" DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
FILES=(-f "$HERE/docker-compose.fork.yml")
if [ -n "${COMPOSE_OVERRIDE:-}" ]; then FILES+=(-f "$HERE/$COMPOSE_OVERRIDE"); fi
mkdir -p "$RUN_DIR"
echo "$PROJECT" > "$RUN_DIR/project.txt"
echo "${COMPOSE_OVERRIDE:-}" > "$RUN_DIR/compose-override.txt"
{
  echo "variant: $VARIANT"
  echo "image: $IMAGE"
  echo "facilitator config: ${FACILITATOR_CONFIG:-facilitator-fork.json}"
  if [ -n "${COMPOSE_OVERRIDE:-}" ]; then echo "compose override: $COMPOSE_OVERRIDE"; fi
  docker image inspect "$IMAGE" --format 'image id: {{.Id}}{{"\n"}}labels: {{json .Config.Labels}}'
} > "$RUN_DIR/image.txt"
docker compose -p "$PROJECT" "${FILES[@]}" up -d --quiet-pull > "$RUN_DIR/compose-up.log" 2>&1
"${PYTHON:-python3}" "$HERE/fork_fund.py" >> "$RUN_DIR/fund.log" 2>&1
for i in $(seq 1 90); do
  if curl -sf -m 3 http://127.0.0.1:19452/supported > "$RUN_DIR/supported.json" 2>/dev/null && curl -sf -m 3 http://127.0.0.1:19453/healthz > /dev/null 2>&1; then
    echo "$RUN_DIR"; exit 0
  fi
  sleep 2
done
echo "stack did not come up; see $RUN_DIR" >&2; exit 1
