#!/usr/bin/env bash
# Run the paying client (app/src/client.ts, reference SDK) in a node container on the host
# network. The buyer's key comes from XD_BUYER_PRIVATE_KEY in the environment.
#   XD_OUT=<jsonl> XD_LABEL=<label> [XD_SERVER=...] [XD_RPC=...] ./client.sh <path> [<path> ...]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${XD_BUYER_PRIVATE_KEY:?}"
OUT="${XD_OUT:?XD_OUT}"; mkdir -p "$(dirname "$OUT")"; touch "$OUT"
OUT_ABS="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
exec docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp -e XD_BUYER_PRIVATE_KEY \
  -e XD_SERVER="${XD_SERVER:-http://127.0.0.1:19453}" -e XD_RPC="${XD_RPC:-http://127.0.0.1:19450}" \
  -e XD_OUT=/out/"$(basename "$OUT_ABS")" -e XD_LABEL="${XD_LABEL:-client}" -e XD_REPEAT_ON_402="${XD_REPEAT_ON_402:-0}" \
  -v "$HERE/../app:/app:ro" -v "$(dirname "$OUT_ABS"):/out" -w /app \
  node:22-bookworm-slim node --import tsx src/client.ts "$@"
