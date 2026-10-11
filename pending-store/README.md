# Follow-up: reconcile the retried `/settle`

With the #136 fix (https://github.com/x402-rs/x402-rs/pull/138), `/settle` answers `settlement_pending` (HTTP 202) with the transaction hash when the receipt cannot be fetched after the broadcast. A resource server on the reference x402 SDK then retries `/settle` once with the same payload (`settleWithPendingRetry` in `@x402/core` 2.28.0). x402-rs verifies that retry from scratch, and once the first transaction has landed it fails with `FiatTokenV2: authorization is used or canceled` (HTTP 500, `unexpected_error`, empty `transaction`). The resource server answers its client 402: the buyer has paid, gets no data, and the hash from the 202 is gone.

The follow-up PR keeps a pending-settlement store in x402-rs, so the retry is reconciled with the transaction already sent: (link to follow). Its branch is `pending-settlement-store` of https://github.com/zachsplat/x402-rs: the #138 commit c6a8680 and one more, c547a34.

This directory has the runs behind it, on Base Sepolia and on an anvil fork of Base Sepolia, and the harness that made them.

## What it shows (2026-10-11)

Base Sepolia, one paid call ($0.01 in Circle's test USDC) per row, two where the app calls again. The facilitator's only RPC is `harness/fault_proxy.py`, which answers HTTP 503 (`-32011 no backend is currently healthy to serve traffic`) to every receipt lookup of the settlement for a window after the broadcast. Resource server on `@x402/express` 2.28.0, client on `@x402/fetch` 2.28.0. "The app calls again" is a second paid call after the 402, as an application might make.

| Fault after broadcast | Facilitator | `/settle` answers | Client got | Paid | Settlement |
|---|---|---|---|---|---|
| none | #138 | 200 | 200 and the data | 0.01 | [0xe543b0c3...2d8c](https://sepolia.basescan.org/tx/0xe543b0c30044dfeadc3a288b5a64a19f2bea8c9fb6f5012167d8656d33a22d8c) |
| 503 for 15 s | #138 | 202, then 500 `unexpected_error` | 402, `unexpected_error`, no hash | 0.01 | [0xf417f27b...991e](https://sepolia.basescan.org/tx/0xf417f27b0e0caf1e246ad4bd768fa4b30821834c58c3353567ae7a012990991e) |
| 503 for 60 s | #138 | the same | the same | 0.01 | [0x05e18f65...0dc4](https://sepolia.basescan.org/tx/0x05e18f65b8cdbdf0365b97bddaf302240c30f0976d893702562abcc37e4d0dc4) |
| 503 for 60 s, the app calls again | #138 | 202, 500, then 200 for the new payment | 402, then 200 and the data | 0.02 for one answer | [0x5bedc270...23ab](https://sepolia.basescan.org/tx/0x5bedc270cb1267ffe9a0791d1d77993bae0b317c5557658135507229c6f323ab), [0x85117cb1...58bf](https://sepolia.basescan.org/tx/0x85117cb1e0e6fb74ec6ecea64f594fa629f6f896d56facf4fa8fa2fc7c7758bf) |
| none | this branch | 200 | 200 and the data | 0.01 | [0x0d60e8af...7e20](https://sepolia.basescan.org/tx/0x0d60e8afa8e32f1903032e2838d65c55054b1d201b95ad566bf2ed13668e7e20) |
| 503 for 15 s | this branch | 202, then 200 with the same hash | 200 and the data | 0.01 | [0x4e232abe...4cce](https://sepolia.basescan.org/tx/0x4e232abeef236ca34ce7e916edf4f8b87c2d96e7cf686a5b94ddf7c80b4b4cce) |
| 503 for 60 s | this branch | 202, then 202 with the same hash | 402, `settlement_pending`, with the hash | 0.01 | [0x9071bf0e...fa09](https://sepolia.basescan.org/tx/0x9071bf0e073456df2664fe2d2f2246bac32641f65ba67995b9ecfc802a6afa09) |
| 503 for 60 s, the app calls again | this branch | 202, 202, then 200 for the new payment | 402 with the hash, then 200 and the data | 0.02 for one answer | [0xd0e55369...fe61](https://sepolia.basescan.org/tx/0xd0e55369f74cbdb7ec54149999983045ff30546f044039914db3c884ad3dfe61), [0x44abefda...8511](https://sepolia.basescan.org/tx/0x44abefda3a5803b4d65b4862572e4ff333aced082db1e2a27d56f48c8f478511) |

I read every settlement above back from https://sepolia.base.org and https://base-sepolia-rpc.publicnode.com at 2026-10-11 23:07Z: status 1, sent by the facilitator's signer, a USDC transfer of 0.01 from the buyer to the seller, and `AuthorizationUsed` for the nonce the client signed (`verified.md` in each live run). The proxy saw one broadcast per paid call (`broadcasts` in `pending-results.jsonl`). The store does not change the last row: the app's second call is a new payment, and it is charged.

On the fork the same verdicts hold, and also for `null` receipts for 60 s and 503 for 120 s. With `receipt_timeout_secs` at 75 instead of the default 30 (`harness/config/facilitator-fork-timeout75.json`), the 60 s outages of 503s and of `null` receipts were delivered, in 60.7 and 60.5 s. `summary.md` has every row of every run.

## Files

- `summary.md`: one table per run (`harness/summarize_pending.py`), the last two being the harness checks described below.
- `logs/live/fault-fix136-20261011T220619Z/` (#138) and `logs/live/fault-pending-store-20261011T221014Z/` (this branch): the Base Sepolia runs. In each: `pending-results.jsonl` (one line per scenario: what the client got, every facilitator exchange, the settlement transactions found through `AuthorizationUsed`, the USDC deltas, the proxy's faults and broadcasts), `pending.log`, `client-*.jsonl` (the client's records: status, decoded `PAYMENT-RESPONSE`, body, and what the chain said about each authorization), `server.log` (the resource server's log, with every facilitator exchange), `facilitator-answers.md` (those exchanges as a table), `verified.md` and `verified.jsonl` (the read-back above), `proxy.log`, `facilitator.log`, `supported.json` and `image.txt`.
- `logs/fork/`: the anvil fork runs, with `anvil.log` and `fund.log`: `fork-fix136-20261011T213329Z` and `fork-fix136-120s-20261011T215903Z` (#138), `fork-pending-store-894e9d7-20261011T215157Z` and `fork-pending-store-timeout75-20261011T221406Z` (this branch), and the two harness checks. The anvil logs list anvil's public development accounts.
- `logs/ci-pending-store/`: the checks of `../harness/ci_checks.sh` on this branch, run from a copy of the script and of `cargo.sh` with other paths (the same commands, in a toolchain image built from the same `../harness/Dockerfile.rust`): `cargo fmt --check`, the release build command from the repository's Dockerfile, the tests of the touched crates and of the workspace, two clippy runs, and a `cargo check` on Rust 1.93.0. Every check exits 0 except `cargo test --workspace` (129 pass, 1 fail): the failure is `networks::tests::permit2_proxies` in `x402-chain-tron`, which also fails on main and in `../logs/ci-fix136/`. The clippy warning counts are the same as on main.
- `harness/` and `app/`: what the runs used; see "Run it".

**Which code ran.** The facilitator images were built from local commits that are not on GitHub, named in each `image.txt` label: ec55c62 has the tree of the #138 head c6a8680 (77ffbb60b4b2cf9d52b0a900e20367fe8efd9e63), and 894e9d7 has the tree of this branch's head c547a34 (ca2fbce10e504715c0e0770df3a35005394364f5), as `git rev-parse <commit>^{tree}` shows. `logs/ci-pending-store/` ran on 894e9d7. Every run used the same two images (the image ids are in `image.txt`).

**What I changed for publishing.** The runs' resource server had two more paid routes that have nothing to do with this; `app/src/server.ts` is that server with only the route the runs paid for (`GET /v1/release-check`, $0.01), answering a fixed record, with the same x402 setup and the same log of facilitator exchanges. In `facilitator.log`, the route's description text inside each logged request body is replaced with `[description removed]`. The harness takes keys from environment variables instead of local key files. `compose-up.log`, `server.console.log` (a copy of `server.log` with Docker's prefixes) and `project.txt` are left out of the run directories, and local paths in the CI logs are shortened. The two `fork-harness-check-*` runs were made afterwards with the published `app/` and `harness/` and throwaway keys, to check that they give the same results: in the 15 s case #138 is paid without delivering and this branch delivers.

## Run it

Requirements: those of `../README.md` (Docker with Compose, git, Python 3.10+ with `httpx` and `eth-account`). Commands run from the repository root unless they `cd`.

```bash
# The facilitator image for this branch, built as in ../README.md; a ../x402-rs checkout next to this repo
git -C ../x402-rs fetch https://github.com/zachsplat/x402-rs pending-settlement-store && git -C ../x402-rs checkout -b pending-store FETCH_HEAD
SRC=../x402-rs harness/ci_checks.sh local-pending-store                 # checks and the release build, logs to logs/ci-local-pending-store/
cp "${XDG_CACHE_HOME:-$HOME/.cache}/x402-rs-136/target-x402-rs-w3-rust_trixie/release/x402-facilitator" harness/
docker build -t w3-x402-facilitator:pending-store -f harness/Dockerfile.runtime --build-arg BINARY=x402-facilitator \
  --label org.opencontainers.image.revision="$(git -C ../x402-rs rev-parse HEAD)" harness
# The resource server's and the client's packages
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/pending-store/app:/app" -w /app node:22-bookworm-slim npm ci
# Keys: any on the fork (fork_up.sh funds them there); on Base Sepolia, a signer with test ETH and a buyer with test USDC
export XD_FACILITATOR_SIGNER=0x... XD_BUYER_PRIVATE_KEY=0x... XD_PAY_TO=0x...
cd pending-store/harness
RUN=$(./fork_up.sh local w3-x402-facilitator:pending-store)             # logs to pending-store/logs/fork/fork-local-<UTC time>/
python pending_test.py --run-dir "$RUN" --label local                    # all six scenarios; --scenarios control,receipt-503-15s for two
./fork_down.sh "$RUN"
python summarize_pending.py "$RUN"
```

The same with the #138 image (`checkout fix136` as in `../README.md`) shows the failure. `FACILITATOR_CONFIG=facilitator-fork-timeout75.json ./fork_up.sh ...` gives the 75 s reconcile wait. `fork_up.sh` runs `fork_fund.py` with `PYTHON` (default `python3`), so with a virtual environment I set `PYTHON=../../.venv/bin/python`. The fork stack uses ports 127.0.0.1:19450 to 19453, the compose project `x402-pending-fork-<variant>`, anvil 1.8.1 (`ANVIL_IMAGE` overrides it) forking https://sepolia.base.org (`FORK_URL` overrides it), `python:3.12-alpine` for the proxy and `node:22-bookworm-slim` for the server.

On Base Sepolia the settlements are real: each paid call moves 0.01 test USDC from the buyer to `XD_PAY_TO`, and the signer pays the gas.

```bash
RUN=$(./livefault_up.sh local w3-x402-facilitator:pending-store)        # ports 127.0.0.1:19461 to 19463, logs to pending-store/logs/live/fault-local-<UTC time>/
CHAIN_RPC=https://base-sepolia-rpc.publicnode.com XD_RPC=https://base-sepolia-rpc.publicnode.com \
  PROXY_URL=http://127.0.0.1:19461 XD_SERVER=http://127.0.0.1:19463 SETTLE_WAIT=10 \
  python pending_test.py --run-dir "$RUN" --label live-local --scenarios control,receipt-503-15s,receipt-503-60s,receipt-503-60s-app-retries
./livefault_down.sh "$RUN"
python verify_pending.py "$RUN" && python facilitator_answers.py "$RUN"
```

The published live runs read the chain through https://base-sepolia-rpc.publicnode.com; reads right after a settlement can hit a lagging backend, which is what `SETTLE_WAIT` is for.
