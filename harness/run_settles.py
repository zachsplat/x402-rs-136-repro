"""Settle x402 payments under injected RPC faults and grade every /settle answer against the chain.

For each settle: arm the fault proxy, sign a fresh EIP-3009 TransferWithAuthorization for Celo
USDC on the anvil fork, POST it to the facilitator's /settle, then read the chain from anvil
directly (never through the proxy): authorizationState(payer, nonce), the AuthorizationUsed log
for that nonce, and the receipt of the transaction that emitted it.

Verdicts:
  SETTLED      success: true, and `transaction` is the hash that consumed the authorization
  PENDING      success: false, errorReason settlement_pending, `transaction` is that hash
  FAILED       success: false, and the authorization was not consumed (nothing landed)
  MISREPORTED  success: false with no usable hash, although the authorization was consumed:
               the payment landed and the answer says it failed (x402-rs #136)
  WRONG        anything else, e.g. a success that did not land or a hash that does not match

The v2-tagged-* scenarios are opt-in (name them in --scenarios). Their payload carries a
`builder-code` extension (x402-rs PR #99, ERC-8021 attribution), and each result records whether
the settlement calldata on chain ends with the ERC-8021 suffix.

Needs eth-account and httpx (pip install eth-account httpx).
  python run_settles.py --label <variant> --out <run dir> [--scenarios a,b] [--reps N]
"""
import argparse
import json
import os
import secrets
import time

import httpx
from eth_account import Account
from eth_utils import keccak, to_checksum_address

FACILITATOR = os.environ.get("FACILITATOR", "http://127.0.0.1:19380")
ANVIL = os.environ.get("ANVIL", "http://127.0.0.1:19345")
PROXY = os.environ.get("PROXY", "http://127.0.0.1:19346")

CHAIN_ID = 42220
USDC = to_checksum_address("0xcebA9300f2b948710d2653dD7B07f33A8B32118C")  # Circle USDC on Celo
# A fresh payer and payee per run. anvil's well-known development accounts 1 and 2 cannot be
# used on a Celo fork: both carry EIP-7702 delegations on Celo mainnet, so USDC checks their
# signatures through EIP-1271 and rejects them. (Account 0, the facilitator's signer in the
# config, has no code there.)
PAYER_KEY = os.environ.get("PAYER_KEY") or "0x" + secrets.token_hex(32)
PAYER = Account.from_key(PAYER_KEY).address
PAY_TO = Account.create().address
AMOUNT = 1000  # 0.001 USDC
AUTH_USED_TOPIC = "0x" + keccak(text="AuthorizationUsed(address,bytes32)").hex()
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
AUTH_STATE_SELECTOR = keccak(text="authorizationState(address,bytes32)")[:4].hex()
ERC8021_MARKER = "80218021802180218021802180218021"  # last 16 bytes of an ERC-8021 suffix
BUILDER_CODE = {"a": "repro136", "s": ["harness"]}  # the payload's builder-code extension

# proxy: the /control body; version: x402 protocol version of the payload
SCENARIOS = {
    "control": {"proxy": {}, "version": 1, "reps": 2,
                "what": "no fault"},
    "receipt-503-short": {"proxy": {"receipt_fault": "503", "window": 2.5}, "version": 1, "reps": 5,
                          "what": "HTTP 503 to every receipt lookup for the 2.5 s after broadcast"},
    "receipt-503-long": {"proxy": {"receipt_fault": "503", "window": 60}, "version": 1, "reps": 5,
                         "what": "HTTP 503 to every receipt lookup for the 60 s after broadcast"},
    "receipt-null-long": {"proxy": {"receipt_fault": "null", "window": 60}, "version": 1, "reps": 3,
                          "what": "result null to every receipt lookup for the 60 s after broadcast"},
    "outage-all-long": {"proxy": {"receipt_fault": "503", "scope": "all", "window": 30}, "version": 1, "reps": 3,
                        "what": "HTTP 503 to every RPC call for the 30 s after broadcast"},
    "send-503": {"proxy": {"send_fault": "503"}, "version": 1, "reps": 3,
                 "what": "HTTP 503 to eth_sendRawTransaction itself: nothing is broadcast"},
    "v2-receipt-503-long": {"proxy": {"receipt_fault": "503", "window": 60}, "version": 2, "reps": 3,
                            "what": "as receipt-503-long, x402 v2 payload"},
    "retry-same-payload": {"proxy": {"receipt_fault": "503", "window": 60}, "version": 1, "reps": 2,
                           "then_retry_same": True,
                           "what": "as receipt-503-long, then the same payload is sent to /settle again with no fault"},
    # Opt-in: not in the default list.
    "v2-tagged-control": {"proxy": {}, "version": 2, "reps": 2, "tag": True, "opt_in": True,
                          "what": "no fault, x402 v2 payload with a builder-code extension"},
    "v2-tagged-receipt-503-long": {"proxy": {"receipt_fault": "503", "window": 60}, "version": 2, "reps": 3,
                                   "tag": True, "opt_in": True,
                                   "what": "as v2-receipt-503-long, with a builder-code extension"},
}


def rpc(method, params=None):
    reply = httpx.post(ANVIL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}, timeout=30).json()
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error']}")
    return reply["result"]


def stamp(t):
    return time.strftime("%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"


def usdc_balance(address):
    data = "0x70a08231" + address[2:].lower().rjust(64, "0")
    return int(rpc("eth_call", [{"to": USDC, "data": data}, "latest"]), 16)


def fund_payer(amount=10_000_000):
    """Give the payer 10 USDC by writing its balance slot on the fork.

    Celo's USDC is Circle's FiatToken v2.2, which packs each balance with a blacklist flag into
    one mapping slot (balanceAndBlacklistStates, storage slot 9), so anvil_dealERC20 cannot find
    it. The slot is keccak256(abi.encode(holder, 9)); the value is the balance with the flag clear.
    """
    slot = "0x" + keccak(bytes.fromhex(PAYER[2:].lower().rjust(64, "0") + "9".rjust(64, "0"))).hex()
    rpc("anvil_setStorageAt", [USDC, slot, "0x" + hex(amount)[2:].rjust(64, "0")])
    balance = usdc_balance(PAYER)
    if balance != amount:
        raise RuntimeError(f"funding failed: balance {balance} after writing slot {slot}")
    return balance


def authorization_used(nonce_hex):
    data = "0x" + AUTH_STATE_SELECTOR + PAYER[2:].lower().rjust(64, "0") + nonce_hex[2:]
    return int(rpc("eth_call", [{"to": USDC, "data": data}, "latest"]), 16) == 1


def authorization_logs(nonce_hex, from_block):
    return rpc("eth_getLogs", [{"address": USDC, "fromBlock": hex(from_block), "toBlock": "latest",
                                "topics": [AUTH_USED_TOPIC, "0x" + PAYER[2:].lower().rjust(64, "0"), nonce_hex]}])


def consuming_tx(nonce_hex, from_block):
    logs = authorization_logs(nonce_hex, from_block)
    return logs[0] if logs else None


def sign_authorization():
    now = int(time.time())
    nonce = "0x" + secrets.token_hex(32)
    message = {"from": PAYER, "to": PAY_TO, "value": AMOUNT, "validAfter": now - 600, "validBefore": now + 3600, "nonce": nonce}
    signed = Account.sign_typed_data(
        PAYER_KEY,
        {"name": "USDC", "version": "2", "chainId": CHAIN_ID, "verifyingContract": USDC},
        {"TransferWithAuthorization": [
            {"name": "from", "type": "address"}, {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"}]},
        message,
    )
    authorization = {"from": PAYER, "to": PAY_TO, "value": str(AMOUNT), "validAfter": str(message["validAfter"]),
                     "validBefore": str(message["validBefore"]), "nonce": nonce}
    return authorization, "0x" + signed.signature.hex().removeprefix("0x")


def settle_request(version, authorization, signature, tag=False):
    evm_payload = {"signature": signature, "authorization": authorization}
    if version == 1:
        requirements = {"scheme": "exact", "network": "celo", "maxAmountRequired": str(AMOUNT),
                        "resource": "https://example.invalid/x402-rs-136", "description": "x402-rs #136 reproduction",
                        "mimeType": "application/json", "payTo": PAY_TO, "maxTimeoutSeconds": 300,
                        "asset": USDC, "extra": {"name": "USDC", "version": "2"}}
        payload = {"x402Version": 1, "scheme": "exact", "network": "celo", "payload": evm_payload}
        return {"x402Version": 1, "paymentPayload": payload, "paymentRequirements": requirements}
    accepted = {"scheme": "exact", "network": f"eip155:{CHAIN_ID}", "amount": str(AMOUNT), "payTo": PAY_TO,
                "maxTimeoutSeconds": 300, "asset": USDC,
                "extra": {"assetTransferMethod": "eip3009", "name": "USDC", "version": "2"}}
    payload = {"x402Version": 2, "accepted": accepted, "payload": evm_payload,
               "resource": {"url": "https://example.invalid/x402-rs-136", "description": "x402-rs #136 reproduction"}}
    if tag:
        payload["extensions"] = {"builder-code": BUILDER_CODE}
    return {"x402Version": 2, "paymentPayload": payload, "paymentRequirements": accepted}


def grade(body, consumed, onchain_tx):
    success = body.get("success") is True
    transaction = body.get("transaction") or ""
    reason = body.get("errorReason")
    if success:
        return "SETTLED" if consumed and transaction == onchain_tx else "WRONG"
    if reason == "settlement_pending":
        return "PENDING" if transaction and transaction == onchain_tx else "WRONG"
    if not consumed:
        return "FAILED"
    return "MISREPORTED"


def wait_ready(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(FACILITATOR + "/supported", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("facilitator did not answer /supported")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scenarios", default=",".join(n for n, s in SCENARIOS.items() if not s.get("opt_in")))
    parser.add_argument("--reps", type=int, default=0, help="override the per-scenario count")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    log_file = open(os.path.join(args.out, "run.log"), "a")
    results_file = open(os.path.join(args.out, "results.jsonl"), "a")

    def log(message):
        line = f"{stamp(time.time())} {message}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    wait_ready()
    fork_block = int(rpc("eth_blockNumber"), 16)
    for address in (PAYER, PAY_TO):
        if rpc("eth_getCode", [address, "latest"]) not in ("0x", "0x0"):
            raise RuntimeError(f"{address} has code on the fork; pick another key")
    balance = fund_payer()
    log(f"=== {args.label}: facilitator {FACILITATOR}, anvil fork of Celo at block {fork_block}, "
        f"payer {PAYER} holds {balance / 1e6:.6f} USDC, pay-to {PAY_TO}")
    totals = {}
    for name in args.scenarios.split(","):
        scenario = SCENARIOS[name]
        reps = args.reps or scenario["reps"]
        log(f"--- scenario {name}: {scenario['what']} (x402 v{scenario['version']}, {reps} settles)")
        for rep in range(1, reps + 1):
            httpx.post(PROXY + "/control", json={}, timeout=5)  # clear any open window first
            authorization, signature = sign_authorization()
            request = settle_request(scenario["version"], authorization, signature, scenario.get("tag", False))
            start_block = int(rpc("eth_blockNumber"), 16)
            httpx.post(PROXY + "/control", json=scenario["proxy"], timeout=5)
            t0 = time.time()
            reply = httpx.post(FACILITATOR + "/settle", json=request, timeout=180)
            t1 = time.time()
            httpx.post(PROXY + "/control", json={}, timeout=5)  # close the window: the answer is in
            try:
                body = reply.json()
            except ValueError:
                body = {"raw": reply.text[:400]}
            # the transaction mines within a block or two; read the chain once it had time to
            deadline = time.time() + 15
            consumed, log_entry = False, None
            while time.time() < deadline:
                consumed = authorization_used(authorization["nonce"])
                log_entry = consuming_tx(authorization["nonce"], start_block)
                if consumed and log_entry:
                    break
                time.sleep(1)
            onchain_tx = log_entry["transactionHash"] if log_entry else None
            receipt = rpc("eth_getTransactionReceipt", [onchain_tx]) if onchain_tx else None
            moved = 0
            if receipt:
                for entry in receipt["logs"]:
                    if entry["topics"][0] == TRANSFER_TOPIC and entry["address"].lower() == USDC.lower():
                        moved += int(entry["data"], 16)
            mined_at = None
            if receipt:
                block = rpc("eth_getBlockByNumber", [receipt["blockNumber"], False])
                mined_at = int(block["timestamp"], 16)
            calldata = rpc("eth_getTransactionByHash", [onchain_tx])["input"] if onchain_tx else ""
            erc8021_suffix = calldata.lower().endswith(ERC8021_MARKER)
            events = [e for e in httpx.get(PROXY + "/events", timeout=5).json() if t0 - 0.5 <= e["t"] <= t1 + 0.5]
            sends = [e for e in events if e["kind"] == "send"]
            faults = [e for e in events if e["kind"] == "fault"]
            verdict = grade(body, consumed, onchain_tx)
            totals.setdefault(name, {}).setdefault(verdict, 0)
            totals[name][verdict] += 1
            result = {
                "label": args.label, "scenario": name, "rep": rep, "verdict": verdict,
                "http_status": reply.status_code, "elapsed_ms": int((t1 - t0) * 1000),
                "response": body, "authorization_nonce": authorization["nonce"],
                "authorization_consumed": consumed, "onchain_tx": onchain_tx,
                "receipt_status": receipt and receipt["status"], "usdc_moved": moved,
                "block": receipt and int(receipt["blockNumber"], 16), "block_time": mined_at,
                "requested_at": stamp(t0), "answered_at": stamp(t1),
                "broadcasts": [s["tx"] for s in sends], "first_broadcast_at": sends[0]["at"] if sends else None,
                "faults_injected": len(faults),
                "erc8021_suffix": erc8021_suffix,
            }
            if scenario.get("then_retry_same"):
                # A caller that retries the very same payload: it must not move money twice.
                again = httpx.post(FACILITATOR + "/settle", json=request, timeout=180)
                time.sleep(3)
                try:
                    again_body = again.json()
                except ValueError:
                    again_body = {"raw": again.text[:400]}
                transfers = len(authorization_logs(authorization["nonce"], start_block))
                result["retry_same_payload"] = {"http_status": again.status_code, "response": again_body,
                                                "authorization_used_logs": transfers}
            results_file.write(json.dumps(result) + "\n")
            results_file.flush()
            short = {k: body.get(k) for k in ("success", "errorReason", "transaction", "network") if k in body}
            log(f"{name} #{rep}: HTTP {reply.status_code} in {result['elapsed_ms']} ms {json.dumps(short)}; "
                f"chain: authorization consumed={consumed} by {onchain_tx} (status {result['receipt_status']}, "
                f"{moved} units moved, block {result['block']}); {len(faults)} faults injected -> {verdict}")
            if verdict in ("MISREPORTED", "WRONG"):
                log(f"    full answer: {json.dumps(body)}")
            if scenario.get("tag"):
                tail = calldata[-160:] if erc8021_suffix else ""
                log(f"    calldata ends with an ERC-8021 suffix: {erc8021_suffix}"
                    + (f"; last 80 bytes 0x...{tail[2:] if tail.startswith('0x') else tail}" if tail else ""))
            if "retry_same_payload" in result:
                again = result["retry_same_payload"]
                log(f"    same payload again: HTTP {again['http_status']} "
                    f"{json.dumps({k: again['response'].get(k) for k in ('success', 'errorReason', 'transaction')})}; "
                    f"AuthorizationUsed logs for the nonce: {again['authorization_used_logs']}")
    log(f"=== {args.label} totals: {json.dumps(totals)}")
    with open(os.path.join(args.out, "totals.json"), "w") as f:
        json.dump(totals, f, indent=2)


if __name__ == "__main__":
    main()
