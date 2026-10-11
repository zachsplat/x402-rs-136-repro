# Reproduction of x402-rs issue #136

When the RPC fails while the facilitator waits for the receipt of a transfer it has already broadcast, `/settle` answers 500 with `unexpected_error` and an empty `transaction`, although the transfer is mined and the USDC has moved: https://github.com/x402-rs/x402-rs/issues/136

The fix: https://github.com/x402-rs/x402-rs/pull/138 (branch `fix-136-settlement-pending` of https://github.com/zachsplat/x402-rs, one commit on main e75adda8).

The harness runs a facilitator image against a local fork of Celo mainnet: anvil forking https://forno.celo.org (chain id 42220, 1 s blocks). The facilitator's only RPC is `harness/fault_proxy.py`, a small JSON-RPC proxy. Once armed, it forwards the next `eth_sendRawTransaction`, so the transfer is broadcast and mined, and then for a set window fails the receipt lookups for that transaction: HTTP 503 with the `-32011 no backend is currently healthy to serve traffic` body quoted in the issue, a `null` result, or a 503 to every call other than `eth_sendRawTransaction`. It can also fail the broadcast itself. `harness/run_settles.py` settles a fresh EIP-3009 `TransferWithAuthorization` of 0.001 USDC (Circle USDC on Celo, 0xcebA9300f2b948710d2653dD7B07f33A8B32118C) for every settle, from a payer and to a payee created for the run, reads the chain from anvil directly (`authorizationState`, the `AuthorizationUsed` log and the transaction that emitted it) and grades the answer.

## What it shows (2026-10-11)

| Scenario (settles) | 2.0.1 image | main e75adda8 | fix |
|---|---|---|---|
| `control`: no fault (2) | 2 SETTLED | 2 SETTLED | 2 SETTLED |
| `receipt-503-short`: 503 to every receipt lookup for the 2.5 s after broadcast (5) | 5 MISREPORTED | 5 MISREPORTED | 5 SETTLED |
| `receipt-503-long`: the same for 60 s (5) | 5 MISREPORTED | 5 MISREPORTED | 5 PENDING |
| `receipt-null-long`: `null` to every receipt lookup for 60 s (3) | 3 MISREPORTED | 3 MISREPORTED | 3 PENDING |
| `outage-all-long`: 503 to every RPC call other than `eth_sendRawTransaction` for 30 s after broadcast (3) | 3 MISREPORTED | 3 MISREPORTED | 3 PENDING |
| `v2-receipt-503-long`: as `receipt-503-long` with an x402 v2 payload (3) | 3 MISREPORTED | 3 MISREPORTED | 3 PENDING |
| `send-503`: 503 to `eth_sendRawTransaction`, nothing broadcast (3) | 3 FAILED | 3 FAILED | 3 FAILED |
| `retry-same-payload`: as `receipt-503-long`, then the same payload to `/settle` again with no fault (2) | 2 MISREPORTED | 2 MISREPORTED | 2 PENDING |

Verdicts, as `run_settles.py` assigns them: SETTLED is success with the hash of the transaction that used the authorization; PENDING is `settlement_pending` with that hash (every PENDING answer in the logs is HTTP 202); FAILED is a failure when nothing landed; MISREPORTED is any other failure although the transfer landed (in every such record `transaction` is empty). In `retry-same-payload` the verdict is for the first answer. The answer to the second `/settle` and the number of `AuthorizationUsed` logs for the nonce (1 in every run) are in each result's `retry_same_payload` field.

## Logs

- `logs/run-stock-2.0.1-20261011T044416Z/`: `ghcr.io/x402-rs/x402-facilitator:2.0.1`, the version in the issue.
- `logs/run-main-e75adda8-20261011T192734Z/`: main at e75adda8. This run also has two opt-in `v2-tagged-*` scenarios that are not in the table.
- `logs/run-fix136-20261011T044725Z/`: the fix.
- `logs/ci-main-e75adda8/`, `logs/ci-fix136/`: `harness/ci_checks.sh` on each tree: `cargo fmt --check`, the release build command from the repository's Dockerfile, the tests of the touched crates and of the workspace, two clippy runs, and a `cargo check` on Rust 1.93.0, the workspace `rust-version`. On both trees every check exits 0 except `cargo test --workspace`, which exits 101 for one test that already fails on main and that the fix does not touch: `networks::tests::permit2_proxies` in `x402-chain-tron` (`crates/chains/x402-chain-tron/src/networks.rs:125`); the tests of the three crates the fix touches pass. A local run of either tree shows the same `test-workspace: exit 101` line in its `summary.txt`.

The fix run and `logs/ci-fix136/` were built from commit e1f51a9, a local commit I amended before opening the PR to reword its message; it is not on GitHub. Its tree is the tree of the branch's single commit c6a8680, 77ffbb60b4b2cf9d52b0a900e20367fe8efd9e63 (`git rev-parse c6a8680^{tree}`), so the code is the same.

Each run directory has `results.jsonl` (one line per settle: the facilitator's answer and what the chain shows), `totals.json`, `image.txt`, and the anvil, proxy and facilitator logs. Local paths in the logs are shortened. The anvil logs list anvil's public development accounts. In three main-run records (`receipt-503-long` rep 5, `receipt-null-long` rep 2, `v2-receipt-503-long` rep 2), `broadcasts` lists two hashes: the first is the previous settle's transaction, caught by the 0.5 s margin the runner adds on each side of a request when it collects broadcasts, and `onchain_tx` is the settle's own transaction. Each authorization was used once. The stock and fix runs were made with an earlier `run_settles.py` that did not write the `erc8021_suffix` field, so their records do not have it; the main run's records do. The published `grade()`, applied to any record of the three runs, gives the verdict that record carries.

## Run it

Requirements: Docker with Compose, git, and Python 3.10+ with `httpx` and `eth-account`. Debian and Ubuntu mark the system interpreter as externally managed, so I install the two packages in a virtual environment, `python3 -m venv .venv && .venv/bin/pip install httpx eth-account` (on Debian and Ubuntu `python3 -m venv` needs the `python3-venv` package), and run `run_all.sh` with that interpreter: `source .venv/bin/activate` first, or `PYTHON=../.venv/bin/python ./run_all.sh ...` from `harness/`.

```bash
git clone https://github.com/x402-rs/x402-rs ../x402-rs && git -C ../x402-rs checkout -B main e75adda8   # main as in the table, next to this repo
git -C ../x402-rs fetch https://github.com/zachsplat/x402-rs fix-136-settlement-pending && git -C ../x402-rs checkout -b fix136 FETCH_HEAD   # the fix (PR #138, commit c6a8680); skip this line to test main
docker build -t w3-rust:trixie -f harness/Dockerfile.rust harness       # rust:trixie with clippy and rustfmt
SRC=../x402-rs harness/ci_checks.sh local                               # checks and the release build, logs to logs/ci-local/
cp "${XDG_CACHE_HOME:-$HOME/.cache}/x402-rs-136/target-x402-rs-w3-rust_trixie/release/x402-facilitator" harness/   # cargo.sh keeps its cargo home and target dirs under that cache dir (SCRATCH overrides it)
docker build -t w3-x402-facilitator:local -f harness/Dockerfile.runtime --build-arg BINARY=x402-facilitator harness
cd harness && ./run_all.sh local w3-x402-facilitator:local               # logs to logs/run-local-<UTC time>/
./run_all.sh stock-2.0.1 ghcr.io/x402-rs/x402-facilitator:2.0.1
```

`ci_checks.sh`, the `cp`, the runtime image build and `run_all.sh` are the same for either tree, and `git -C ../x402-rs checkout main` or `git -C ../x402-rs checkout fix136` switches between them. To build both from the one checkout I run them once per tree with labels of my own, such as `local-main` and `local-fix`; the published labels `main-e75adda8` and `fix136` would overwrite `logs/ci-main-e75adda8/` and `logs/ci-fix136/` in this clone.

`Dockerfile.runtime` is the runtime stage of the repository's Dockerfile with the binary copied in, so one build serves both the checks and the runs. `cargo.sh` gives the toolchain container the Docker daemon's CPUs, at most 6 (`CPUS` overrides it). `run_all.sh` takes optional scenario names and a repetition count, pulls the facilitator image if it is not present, uses the compose project `w3-x402-<variant>` (characters outside `a-z0-9_-` become `-`, so `stock-2.0.1` runs as `w3-x402-stock-2-0-1`) with ports 127.0.0.1:19345 (anvil), 19346 (proxy) and 19380 (facilitator), and removes the containers and volumes when it ends. Compose pulls `ghcr.io/foundry-rs/foundry:v1.8.1`, the anvil version in the published anvil logs, and `python:3.12-alpine` on the first run. `FORK_URL` overrides the Celo RPC.

The difference from the report in the issue: a local fork and a proxy that injects the failures, instead of an RPC provider outage on Celo mainnet.

## Follow-up: the retried `/settle`

With the fix, a resource server on the reference x402 SDK retries `/settle` once after a `settlement_pending` answer, and x402-rs verifies that retry from scratch. Once the transfer has landed the retry fails, so the buyer pays and gets a 402 with no hash. The follow-up PR, stacked on #138, keeps a pending-settlement store so the retry is reconciled with the transaction already sent: (link to follow). Its Base Sepolia runs, logs and harness are in [`pending-store/`](pending-store/).

## License

MIT.
