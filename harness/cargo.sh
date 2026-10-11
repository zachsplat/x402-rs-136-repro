#!/usr/bin/env bash
# Run cargo for the x402-rs tree inside the toolchain container, as the calling user,
# capped at CPUS build jobs and CPUs (default: the Docker daemon's CPU count, at most 6).
#   SRC=<path to x402-rs checkout> TARGET=<target dir> ./cargo.sh <cargo args...>
# IMAGE defaults to w3-rust:trixie (build it with: docker build -t w3-rust:trixie -f Dockerfile.rust .)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRATCH="${SCRATCH:-${XDG_CACHE_HOME:-$HOME/.cache}/x402-rs-136}"  # cargo home and target dirs
SRC="${SRC:-$HERE/../../x402-rs}"
SRC_ABS="$(cd "$SRC" && pwd)"
# One target dir per checkout and toolchain: cargo keys workspace crates by their path inside
# the workspace, so two checkouts sharing a target dir reuse each other's artifacts whenever
# the files of the current one are older.
IMAGE="${IMAGE:-w3-rust:trixie}"
TARGET="${TARGET:-$SCRATCH/target-$(basename "$SRC_ABS")-$(printf %s "$IMAGE" | tr -c 'a-zA-Z0-9.-' '_')}"
mkdir -p "$SCRATCH/cargo-home" "$TARGET"
if [ -z "${CPUS:-}" ]; then
  CPUS="$(docker info --format '{{.NCPU}}')"  # docker refuses --cpus above the daemon's CPU count
  if [ "$CPUS" -gt 6 ]; then CPUS=6; fi
fi
exec docker run --rm --user "$(id -u):$(id -g)" --cpus "$CPUS" \
  -e CARGO_HOME=/cargo-home -e CARGO_TARGET_DIR=/target -e CARGO_BUILD_JOBS="$CPUS" \
  -e CARGO_NET_GIT_FETCH_WITH_CLI=true -e HOME=/tmp -e CARGO_TERM_COLOR=never \
  -v "$SCRATCH/cargo-home:/cargo-home" -v "$TARGET:/target" -v "$SRC_ABS:$SRC_ABS" -w "$SRC_ABS" \
  "$IMAGE" cargo "$@"
