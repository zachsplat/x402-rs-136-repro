#!/usr/bin/env bash
# The checks run on each branch: formatting, the image build command from the repository's
# Dockerfile (what its CI runs), the unit tests of the touched crates and of the workspace,
# clippy over the workspace and over x402-chain-eip155 with its facilitator code enabled,
# and a cargo check on the workspace's rust-version (1.93.0).
#   ./ci_checks.sh <label>     (runs against SRC, default ../../x402-rs; logs to ../logs/ci-<label>/)
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="${1:?label}"
OUT="$HERE/../logs/ci-$LABEL"
mkdir -p "$OUT"
SRC_DIR="$(cd "${SRC:-$HERE/../../x402-rs}" && pwd)"
export SRC="$SRC_DIR"
echo "source $(git -C "$SRC_DIR" rev-parse HEAD) ($(git -C "$SRC_DIR" branch --show-current))" > "$OUT/summary.txt"
"$HERE/cargo.sh" --version >> "$OUT/summary.txt" 2>&1
IMAGE=rust:1.93.0-bookworm "$HERE/cargo.sh" --version | sed 's/^/msrv /' >> "$OUT/summary.txt" 2>&1
run() {
  local name="$1"; shift
  local start=$(date +%s)
  "$@" > "$OUT/$name.log" 2>&1
  local code=$?
  echo "$name: exit $code ($(( $(date +%s) - start )) s): $*" | tee -a "$OUT/summary.txt"
}
C="$HERE/cargo.sh"
run fmt          "$C" fmt --all --check
run build        "$C" build --package x402-facilitator --features full --release --locked
run test-types   "$C" test -p x402-types --locked
run test-eip155  "$C" test -p x402-chain-eip155 --features full --locked
run test-local   "$C" test -p x402-facilitator-local --locked
run test-workspace "$C" test --workspace --no-fail-fast --locked
run clippy-workspace "$C" clippy --workspace --all-targets --locked
run clippy-eip155-full "$C" clippy -p x402-chain-eip155 --features full --all-targets --locked
run msrv-check   env IMAGE=rust:1.93.0-bookworm "$C" check -p x402-types -p x402-facilitator-local -p x402-facilitator --features x402-chain-eip155/full --locked
grep -hE '^test result|FAILED|failures:' "$OUT"/test-*.log >> "$OUT/summary.txt"
grep -hcE '^(warning|error)(\[|:)' "$OUT"/clippy-*.log | paste -sd' ' | sed 's/^/clippy warning+error line counts (workspace, eip155-full): /' >> "$OUT/summary.txt"
