# Follow-up: a retried `/settle` the store cannot answer

The pending-settlement store of https://github.com/x402-rs/x402-rs/pull/140 lives in the facilitator process. A retry that reaches another instance, or the same one after a restart, finds no entry, is settled from scratch and fails once the first transfer has landed (`FiatTokenV2: authorization is used or canceled`): the buyer has paid and the resource server answers 402 with no hash. In the PR thread I offered to answer such a retry from the chain instead (https://github.com/x402-rs/x402-rs/pull/140#issuecomment-6342369212). The branch `eip3009-chain-fallback` of https://github.com/zachsplat/x402-rs does that: one commit, a15d29a, on the PR's head c547a34.

## What the branch does

With `reconcile_used_authorizations` set for the chain (off by default), a settle request that has no store entry and fails is looked up on chain, for ERC-3009 payments only:

1. `authorizationState(from, nonce)` on the asset. An unused authorization stops here (one call).
2. The blocks that can hold the use: after `validAfter`, before `validBefore`, and within the last five minutes (the store's TTL), found from block timestamps.
3. `eth_getLogs` for `AuthorizationUsed(from, nonce)` on the asset, 100 blocks per call, newest first, at most 50 calls.
4. The receipt of the transaction found, waited for as the store's reconcile waits (`receipt_timeout_secs`).
5. Success with that hash if the transaction succeeded, was sent by one of the facilitator's signers, and the asset emitted a `Transfer` of the signed value from the payer to the recipient. If the receipt is still unavailable, `settlement_pending` (202) with that hash, not recorded in the store, so the next retry is checked again. Anything else fails as before.

The lookup runs only when the request matches its requirements (network, recipient, amount) and not after a receipt failure, which the store records as before. Permit2 payments are not covered: their nonces are kept in the Permit2 contract and need their own lookup.

## What it costs, and why it is off by default

The facilitator cannot tell the retry of a settlement whose store entry is elsewhere from another copy of a payment it already settled. So with the option on, for five minutes after a settlement, `/settle` answers success with the same hash to any request that carries that authorization and matches its requirements.

- Verifying before settling protects a resource server only from a copy that arrives after the settlement has landed, because `/verify` of a used authorization fails. The reference SDK middleware (`@x402/express` 2.28.0) and `x402-axum` by default verify, run the handler, then settle, and neither holds back a second request that carries the same payment. A copy that passes `/verify` before the settlement lands and reaches `/settle` after it is answered with the first copy's hash, and the server serves it too. The `copies-during-work` rows below show it: the handler works 6 s, the second copy is sent 3 s after the first, and with the option on both copies get the data for one payment. Copies sent at the same time are a race (`copies-at-once`, three times per run): the second copy is answered from the chain only if the first settlement has been mined by the time the second copy's settle fails, which happened in one of the three runs with the option on.
- A server that settles without verifying (`x402-axum` with `settle_before_execution`) would also serve a copy sent later (`settle-replay`).
- Two guarantees in #140's description no longer hold with the option on: two copies of the same retry cannot both answer success (the copy that finds no entry can answer from the chain), and a signature re-sent with other requirements settles from scratch and fails instead of inheriting another request's settlement (with the same network, asset and recipient and an amount the authorization covers, it is answered with the earlier settlement, and the original request keeps its store entry for its own retry). The unit test `test_same_signature_in_another_matching_request_answers_the_transaction_found` shows the second.
- A failed settle of a request that matches its requirements costs one `authorizationState` call; with a used authorization, also the latest block, a few block headers and up to 50 `eth_getLogs` calls (about 15 for five minutes of Base Sepolia's 0.2 s blocks). Used authorizations are public and the caller of `/settle` supplies the requirements, so anyone who can call `/settle` can make that search run; a public `/settle` with the option on should be rate-limited.

## What it shows (2026-10-22)

Anvil fork of Base Sepolia, one paid call ($0.01 in Circle's test USDC) per row, with the harness of [`README.md`](README.md) and these additions:

- `harness/settle_lb.py` sits between the resource server and the facilitator (`harness/docker-compose.restart.yml`) and, in the `*-restart` rows, restarts the facilitator container between its 202 `settlement_pending` and the resource server's retry, so the retry reaches a new process with an empty store. In `settle-replay` it keeps the payment's `/verify` and `/settle` requests, and `harness/pending_test.py` sends them to the facilitator again after the paid call.
- In the `copies-*` rows the client (`app/src/client.ts`, `XD_COPIES=2`) sends its paid request twice with the same `PAYMENT-SIGNATURE` header: at the same time in `copies-at-once`, and 3 s apart in `copies-during-work`, where the resource server's handler works 6 s before it answers (`work_ms=6000` in `app/src/server.ts`). The second copy is then verified while the first is still in its handler, and reaches `/settle` after the first settlement has landed. `MORE_ANSWERS_THAN_PAID` means both copies got the data for one payment.

Both runs use the same image, built from a15d29a; the second runs with the option off, which is the default and settles as #140 alone.

### fork-chain-fallback-reconcile-20261022T173521Z (anvil fork of Base Sepolia)

`image: w3-x402-facilitator:chain-fallback`, `facilitator config: facilitator-fork-reconcile.json`, `labels: {"org.opencontainers.image.revision":"a15d29ae83dbef53dd61d6ea69405d5e23e82756"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 7.7 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x192919a6...5dc2` |
| receipt-503-15s | 200 success tx=yes | 15.3 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xbd4a336a...8105` |
| receipt-503-15s-restart | 200 success tx=yes | 16.1 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xd7eb7d2e...c038` |
| receipt-503-60s-restart | 402 settlement_pending tx=yes | 37.2 | 202 settlement_pending, 202 settlement_pending | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0x0e0a4e77...5217` |
| settle-replay | 200 success tx=yes | 0.4 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x72ac2cb3...2d04` |
| copies-at-once | 200 success tx=yes; 200 success tx=yes | 6.0, 6.5 | 200 success, 200 success | 1 x, seller +0.01 USDC | 2 | **MORE_ANSWERS_THAN_PAID** | `0x1d0ce2b7...5c0f` |
| copies-at-once | 200 success tx=yes; 402 unexpected_error tx=empty | 5.9, 0.3 | 500 unexpected_error, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x95533bce...227d` |
| copies-at-once | 402 unexpected_error tx=empty; 200 success tx=yes | 0.2, 7.2 | 500 unexpected_error, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x964c0173...f7b3` |
| copies-during-work | 200 success tx=yes; 200 success tx=yes | 12.6, 6.4 | 200 success, 200 success | 1 x, seller +0.01 USDC | 2 | **MORE_ANSWERS_THAN_PAID** | `0xe820f6ee...03ff` |

receipt-503-15s-restart: the facilitator was restarted after its 202 and answered again 0.44 s later.

receipt-503-60s-restart: the facilitator was restarted after its 202 and answered again 0.43 s later.

settle-replay: the payment's /settle sent again: 200 success 0x72ac2cb3...2d04.

settle-replay: the payment's /verify sent again: 500 unexpected_error.

copies-at-once: copy 1 at 0 s, copy 2 at 0 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+0.0 s); /settle 200 success 0x1d0ce2b7...5c0f (+5.9 s); /settle 200 success 0x1d0ce2b7...5c0f (+6.4 s).

copies-at-once: copy 1 at 0 s, copy 2 at 0 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+0.0 s); /settle 500 unexpected_error (+0.2 s); /settle 200 success 0x95533bce...227d (+5.8 s).

copies-at-once: copy 1 at 0 s, copy 2 at 0 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+0.0 s); /settle 500 unexpected_error (+0.1 s); /settle 200 success 0x964c0173...f7b3 (+7.2 s).

copies-during-work: copy 1 at 0 s, copy 2 at 3.001 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+3.0 s); /settle 200 success 0xe820f6ee...03ff (+9.3 s); /settle 200 success 0xe820f6ee...03ff (+12.5 s).

### fork-chain-fallback-default-20261022T173839Z (anvil fork of Base Sepolia)

`image: w3-x402-facilitator:chain-fallback`, `facilitator config: facilitator-fork.json`, `labels: {"org.opencontainers.image.revision":"a15d29ae83dbef53dd61d6ea69405d5e23e82756"}`

| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |
|---|---|---|---|---|---|---|---|
| control | 200 success tx=yes | 7.6 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x5abad8de...772a` |
| receipt-503-15s | 200 success tx=yes | 15.3 | 202 settlement_pending, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xb53dfbde...e5ce` |
| receipt-503-15s-restart | 402 unexpected_error tx=empty | 7.7 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0xcba23cbd...41a1` |
| receipt-503-60s-restart | 402 unexpected_error tx=empty | 7.7 | 202 settlement_pending, 500 unexpected_error | 1 x, seller +0.01 USDC | 0 | **PAID_NOT_DELIVERED** | `0x99ee43b3...0637` |
| settle-replay | 200 success tx=yes | 7.3 | 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xe56f2a9e...5d58` |
| copies-at-once | 402 unexpected_error tx=empty; 200 success tx=yes | 0.2, 7.2 | 500 unexpected_error, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0xe3734665...e815` |
| copies-at-once | 402 unexpected_error tx=empty; 200 success tx=yes | 5.6, 5.6 | 200 success, 500 unexpected_error | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x366d7115...1316` |
| copies-at-once | 200 success tx=yes; 402 unexpected_error tx=empty | 6.4, 0.2 | 500 unexpected_error, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x6fda5f7d...615c` |
| copies-during-work | 200 success tx=yes; 402 unexpected_error tx=empty | 13.3, 6.1 | 500 unexpected_error, 200 success | 1 x, seller +0.01 USDC | 1 | **DELIVERED** | `0x21efa917...12f0` |

receipt-503-15s-restart: the facilitator was restarted after its 202 and answered again 0.42 s later.

receipt-503-60s-restart: the facilitator was restarted after its 202 and answered again 0.43 s later.

settle-replay: the payment's /settle sent again: 500 unexpected_error.

settle-replay: the payment's /verify sent again: 500 unexpected_error.

copies-at-once: copy 1 at 0 s, copy 2 at 0 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+0.0 s); /settle 500 unexpected_error (+0.1 s); /settle 200 success 0xe3734665...e815 (+7.2 s).

copies-at-once: copy 1 at 0 s, copy 2 at 0 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+0.0 s); /settle 200 success 0x366d7115...1316 (+5.5 s); /settle 500 unexpected_error (+5.5 s).

copies-at-once: copy 1 at 0 s, copy 2 at 0 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+0.0 s); /settle 500 unexpected_error (+0.1 s); /settle 200 success 0x6fda5f7d...615c (+6.3 s).

copies-during-work: copy 1 at 0 s, copy 2 at 3.001 s; the resource server's exchanges with the facilitator, in the order answered (time of the answer): /verify 200 valid (+0.0 s); /verify 200 valid (+2.9 s); /settle 500 unexpected_error (+9.0 s); /settle 200 success 0x21efa917...12f0 (+13.2 s).

With the option on, the 15 s restart row is delivered with the hash of the first answer. In the 60 s restart row the receipt is still unavailable after the new process has waited for it (30 s), so it answers 202 with the hash it found on chain, which is what the store answers for a 60 s outage without a restart (#140's table). With the option off, both restart rows end as they do without the store: 202, then 500 with no hash, and the buyer pays for nothing.

The copies rows show the cost. With the option off, every copy after the first fails at `/settle` and gets a 402, so each payment is served once. With the option on, `copies-during-work` serves both copies, and so does the first `copies-at-once` row: there both copies' transactions were sent, the second (`0x5cd1c8b4...303c`, in `proxy.log`) reverted on the used authorization, and the facilitator answered it with the first (`facilitator.log`: "Settle request answered with the transaction that used its authorization"). In the other two `copies-at-once` rows the second copy's settle failed before the first transaction was mined, so the lookup found nothing and the copy failed as with the option off.

`facilitator-answers.md` in each run directory lists every exchange with the facilitator; `lb.log` lists the restarts and the replayed requests; `pending-results.jsonl` has each row in full, with the settlement transactions read from anvil through `AuthorizationUsed`; `client-*.jsonl` has what the client got for each copy.

## What the harness caught on the way

Three earlier builds of the branch are in `logs/fork/superseded/`; none of those commits was published.

- `fork-chain-fallback-reconcile-20261022T163356Z` (644c471): the log queries covered up to 1,000 blocks, and every lookup failed with `eth_getLogs is limited to a 200 range`. Anvil sends log queries for blocks before the fork point to https://sepolia.base.org, which caps the range at 200 blocks, and Base Sepolia makes a block every 0.2 s (block 48830250 at 1792687918, block 48830350 at 1792687938), so five minutes is about 1,500 blocks. The branch now queries 100 blocks at a time.
- `fork-chain-fallback-reconcile-20261022T163907Z` (3a93dd5): when the receipt of the transaction found was still unavailable, the retry answered 500 and the hash was lost (the 60 s restart row). It now answers 202 with that hash.
- `fork-chain-fallback-reconcile-20261022T164520Z` and `fork-chain-fallback-default-20261022T164812Z` (aa89172): the same facilitator code as a15d29a, which only rewords the documentation of the option and adds the unit test above. Those runs had no copies rows, and the documentation said that servers which verify before settling are not affected. The `copies-*` rows show that this holds only for a copy that arrives after the settlement has landed.

## Run it

As in [`README.md`](README.md), with the image built from the branch and the override file:

```bash
git -C ../x402-rs fetch https://github.com/zachsplat/x402-rs eip3009-chain-fallback && git -C ../x402-rs checkout -b chain-fallback FETCH_HEAD
# build the binary and the image as in README.md, tagged w3-x402-facilitator:chain-fallback
cd pending-store/harness
RUN=$(COMPOSE_OVERRIDE=docker-compose.restart.yml FACILITATOR_CONFIG=facilitator-fork-reconcile.json ./fork_up.sh chain-fallback-reconcile w3-x402-facilitator:chain-fallback)
python pending_test.py --run-dir "$RUN" --label chain-fallback-reconcile --scenarios control,receipt-503-15s,receipt-503-15s-restart,receipt-503-60s-restart,settle-replay,copies-at-once,copies-at-once,copies-at-once,copies-during-work
./fork_down.sh "$RUN"
python summarize_pending.py "$RUN" && python facilitator_answers.py "$RUN"
```

Without `FACILITATOR_CONFIG` the facilitator runs with the option off. `settle_lb.py` restarts the facilitator through the Docker Engine socket, which `docker-compose.restart.yml` mounts into its container, so run it on a machine you own; its control endpoint is 127.0.0.1:19454.

The checks of the branch (formatting, the release build, tests, clippy, and a `cargo check` on Rust 1.93.0) are in `logs/ci-chain-fallback/`: `cargo test -p x402-chain-eip155 --features full` passes 63 unit tests and 3 doc tests, and `cargo test --workspace` fails only `x402-chain-tron` `networks::tests::permit2_proxies`, as on main.
