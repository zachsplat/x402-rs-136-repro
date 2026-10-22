"""What a paying client sees when the facilitator answers settlement_pending.

Runs against a stack from fork_up.sh or livefault_up.sh: the reference-SDK resource server
(app/src/server.ts) in front of the x402-rs facilitator under test, whose only RPC is the fault
proxy. Per scenario:
arm the proxy (503 to every receipt lookup of the next broadcast transaction for a window), make
one paid call with the reference-SDK client (app/src/client.ts), wait out the window, then read
the chain from anvil directly (never through the proxy) and the resource server's log of its
facilitator exchanges.

Grades, per paid call:
  DELIVERED            200 with the data, and the buyer's authorization was used once
  PAID_NOT_DELIVERED   no data, but the authorization was used: the buyer paid for nothing
  NOT_PAID             no data, and the authorization was not used
A scenario with --repeat also lets the client call again after a 402, as an app would; if both
authorizations are used for one answer, the scenario is DOUBLE_CHARGED. In the copies-* scenarios
the client sends its paid request twice with the same PAYMENT-SIGNATURE header (one payment); if
both copies get the data, the scenario is MORE_ANSWERS_THAN_PAID.

The *-restart scenarios and settle-replay need the stack with docker-compose.restart.yml
(settle_lb.py between the resource server and the facilitator, control at LB_URL). In the
*-restart scenarios the facilitator container is restarted between its 202 settlement_pending
and the resource server's retry, so the retry reaches a process with an empty pending store.
settle-replay makes a paid call with no fault, then sends the /settle and /verify requests of
that payment to the facilitator again (FACILITATOR_URL), as a replayed payment would reach a
resource server that settles without verifying, and records the answers.

copies-at-once sends the two copies at the same time to the resource server, whose handler answers
at once. copies-during-work asks the handler to work 6 s before it answers (work_ms) and sends the
second copy 3 s after the first: the second copy is verified while the first is still in its
handler, before its settlement is sent, and reaches /settle after that settlement has landed
(anvil makes a block every 2 s).

  python pending_test.py --run-dir <run dir> --label <image label> [--scenarios a,b] [--path P]

The buyer is the address of XD_BUYER_PRIVATE_KEY and the seller is XD_PAY_TO. For a live stack,
point CHAIN_RPC (chain reads) and the client's XD_RPC at a Base Sepolia endpoint, PROXY_URL at
http://127.0.0.1:19461 and XD_SERVER at http://127.0.0.1:19463; SETTLE_WAIT adds seconds before
the chain is read, since public endpoints can lag right after a settlement.
"""
import argparse
import json
import os
import subprocess
import time

import httpx
from eth_account import Account
from eth_utils import keccak

HERE = os.path.dirname(os.path.abspath(__file__))
ANVIL = os.environ.get("CHAIN_RPC", "http://127.0.0.1:19450")  # chain reads, never through the proxy
PROXY = os.environ.get("PROXY_URL", "http://127.0.0.1:19451")
LB = os.environ.get("LB_URL", "http://127.0.0.1:19454")
FACILITATOR = os.environ.get("FACILITATOR_URL", "http://127.0.0.1:19452")
SETTLE_WAIT = float(os.environ.get("SETTLE_WAIT", "0"))  # extra wait before reading a public chain
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
AUTH_USED = "0x" + keccak(text="AuthorizationUsed(address,bytes32)").hex()

SCENARIOS = {
    "control": {"proxy": {}, "repeat": False, "what": "no fault"},
    "receipt-503-15s": {"proxy": {"receipt_fault": "503", "window": 15}, "repeat": False,
                        "what": "HTTP 503 to every receipt lookup of the settlement for 15 s after broadcast"},
    "receipt-503-60s": {"proxy": {"receipt_fault": "503", "window": 60}, "repeat": False,
                        "what": "HTTP 503 to every receipt lookup of the settlement for 60 s after broadcast"},
    "receipt-503-60s-app-retries": {"proxy": {"receipt_fault": "503", "window": 60}, "repeat": True,
                                    "what": "as receipt-503-60s; the client calls again after the 402, as an app would"},
    "receipt-null-60s": {"proxy": {"receipt_fault": "null", "window": 60}, "repeat": False,
                         "what": "result null to every receipt lookup of the settlement for 60 s after broadcast"},
    "receipt-503-120s": {"proxy": {"receipt_fault": "503", "window": 120}, "repeat": False,
                         "what": "HTTP 503 to every receipt lookup of the settlement for 120 s after broadcast"},
    "receipt-503-15s-restart": {"proxy": {"receipt_fault": "503", "window": 15}, "repeat": False,
                                "lb": {"restart_on_pending": True},
                                "what": "as receipt-503-15s; the facilitator restarts between its 202 and the retry"},
    "receipt-503-60s-restart": {"proxy": {"receipt_fault": "503", "window": 60}, "repeat": False,
                                "lb": {"restart_on_pending": True},
                                "what": "as receipt-503-60s; the facilitator restarts between its 202 and the retry"},
    "settle-replay": {"proxy": {}, "repeat": False, "lb": {}, "replay": True,
                      "what": "no fault; then the payment's /settle and /verify requests are sent to the facilitator again"},
    "copies-at-once": {"proxy": {}, "repeat": False, "copies": 2, "copy_gap_ms": 0,
                       "what": "no fault; two copies of one paid request (same PAYMENT-SIGNATURE) sent at the same time"},
    "copies-during-work": {"proxy": {}, "repeat": False, "copies": 2, "copy_gap_ms": 3000, "work_ms": 6000,
                           "what": "no fault; the handler works 6 s; the second copy of the paid request is sent 3 s after the first"},
}


def rpc(method, params):
    reply = httpx.post(ANVIL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30).json()
    if "error" in reply:
        raise RuntimeError(f"{method}: {reply['error']}")
    return reply["result"]


def usdc(holder):
    return int(rpc("eth_call", [{"to": USDC, "data": "0x70a08231" + holder[2:].lower().rjust(64, "0")}, "latest"]), 16)


def auth_logs(buyer, nonce, from_block):
    return rpc("eth_getLogs", [{"address": USDC, "fromBlock": hex(from_block), "toBlock": "latest",
                                "topics": [AUTH_USED, "0x" + buyer[2:].lower().rjust(64, "0"), nonce]}])


def server_log_since(run_dir, since_iso):
    out = []
    path = os.path.join(run_dir, "server.log")
    if not os.path.exists(path):
        return out
    for line in open(path):
        entry = json.loads(line)
        if entry.get("t", "") >= since_iso and entry.get("kind") in ("facilitator", "settled", "settle_failure"):
            out.append(entry)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--path", default="/v1/release-check?image=openzeppelin-relayer@30b32b1")
    args = parser.parse_args()
    run_dir = os.path.abspath(args.run_dir)
    buyer, seller = Account.from_key(os.environ["XD_BUYER_PRIVATE_KEY"]).address, os.environ["XD_PAY_TO"]
    out_path = os.path.join(run_dir, "pending-results.jsonl")
    log_path = os.path.join(run_dir, "pending.log")
    log_file = open(log_path, "a")

    def log(message):
        line = f"{time.strftime('%H:%M:%SZ', time.gmtime())} {message}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    log(f"=== {args.label}: path {args.path}, buyer {buyer}, seller {seller}")
    runs = {}
    for name in args.scenarios.split(","):
        scenario = SCENARIOS[name]
        runs[name] = runs.get(name, 0) + 1  # a scenario listed again gets its own client file
        httpx.post(PROXY + "/control", json={}, timeout=5)
        if "lb" in scenario:
            httpx.post(LB + "/control", json=scenario["lb"], timeout=5)
        start_block = int(rpc("eth_blockNumber", []), 16)
        seller_before, buyer_before = usdc(seller), usdc(buyer)
        now = time.time()
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now * 1000) % 1000:03d}Z"
        httpx.post(PROXY + "/control", json=scenario["proxy"], timeout=5)
        client_out = os.path.join(run_dir, f"client-{args.label}-{name}{'' if runs[name] == 1 else '-' + str(runs[name])}.jsonl")
        if os.path.exists(client_out):
            os.remove(client_out)
        env = dict(os.environ, XD_OUT=client_out, XD_LABEL=f"{args.label}:{name}",
                   XD_REPEAT_ON_402="1" if scenario["repeat"] else "0",
                   XD_COPIES=str(scenario.get("copies", 1)), XD_COPY_GAP_MS=str(scenario.get("copy_gap_ms", 0)))
        path = args.path + (f"{'&' if '?' in args.path else '?'}work_ms={scenario['work_ms']}" if scenario.get("work_ms") else "")
        t0 = time.time()
        subprocess.run([os.path.join(HERE, "client.sh"), path], env=env, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        elapsed = time.time() - t0
        window = float(scenario["proxy"].get("window", 0))
        if window:
            time.sleep(max(0.0, window - elapsed) + 6)  # let the window close and the chain settle
        time.sleep(SETTLE_WAIT)
        httpx.post(PROXY + "/control", json={}, timeout=5)
        lb_events = []
        if "lb" in scenario:
            httpx.post(LB + "/control", json={}, timeout=5)
            lb_events = [e for e in httpx.get(LB + "/events", timeout=5).json() if e["t"] >= t0 - 1]
        replays = []
        if scenario.get("replay"):
            sent = {e["path"]: e["request"] for e in reversed(lb_events) if e["kind"] == "exchange"}
            for path in ("/settle", "/verify"):
                if path in sent:
                    r = httpx.post(FACILITATOR + path, json=sent[path], timeout=180)
                    try:
                        body = r.json()
                    except ValueError:
                        body = r.text[:500]
                    replays.append({"path": path, "status": r.status_code, "body": body})
                    log(f"{name}: replayed {path}: {r.status_code} {json.dumps(body)[:300]}")
        calls = [json.loads(line) for line in open(client_out) if '"kind":"call"' in line.replace(" ", "")]
        nonces = list(dict.fromkeys(p["nonce"] for c in calls for p in c.get("payments", [])))  # copies share one
        onchain = {n: [l["transactionHash"] for l in auth_logs(buyer, n, start_block)] for n in nonces}
        seller_after, buyer_after = usdc(seller), usdc(buyer)
        exchanges = server_log_since(run_dir, since)
        events = [e for e in httpx.get(PROXY + "/events", timeout=5).json() if e["t"] >= t0 - 1]
        graded = []
        for call in calls:
            used = [n for n in (p["nonce"] for p in call.get("payments", [])) if onchain.get(n)]
            delivered = call["status"] == 200
            grade = "DELIVERED" if delivered and used else "PAID_NOT_DELIVERED" if used else "NOT_PAID"
            graded.append({"attempt": call["attempt"], "copy": call.get("copy", 1), "sent_after_ms": call.get("sent_after_ms"),
                           "status": call["status"], "ms": call["ms"], "grade": grade,
                           "payment_response": call.get("payment_response"),
                           "body": call.get("body") if not delivered else "(data)",
                           "nonces": [p["nonce"] for p in call.get("payments", [])], "authorizations_used": len(used)})
        answers = sum(1 for g in graded if g["grade"] == "DELIVERED")
        paid = sum(1 for n in nonces if onchain.get(n))
        verdict = ("MORE_ANSWERS_THAN_PAID" if answers > paid else
                   "DOUBLE_CHARGED" if paid > answers and answers else
                   "PAID_NOT_DELIVERED" if paid > answers else
                   "DELIVERED" if answers else "NOT_PAID")
        result = {
            "label": args.label, "scenario": name, "what": scenario["what"], "path": path, "verdict": verdict,
            "calls": graded, "authorizations_signed": len(nonces), "authorizations_used": paid, "answers": answers,
            "settlement_txs": onchain,
            "seller_usdc_delta": seller_after - seller_before, "buyer_usdc_delta": buyer_after - buyer_before,
            "facilitator_exchanges": [
                {k: e.get(k) for k in ("t", "path", "status", "ms")} | {
                    "body": {k: (e.get("body") or {}).get(k) for k in ("success", "errorReason", "transaction", "network", "errorMessage", "isValid", "invalidReason")}
                    if isinstance(e.get("body"), dict) else e.get("body")}
                for e in exchanges if e.get("kind") == "facilitator"],
            "proxy_faults": sum(1 for e in events if e["kind"] == "fault"),
            "broadcasts": [e["tx"] for e in events if e["kind"] == "send"],
            "restarts": [{k: e.get(k) for k in ("t", "seconds", "up", "docker_status")} for e in lb_events if e["kind"] == "restart"],
            "replays": replays,
        }
        with open(out_path, "a") as f:
            f.write(json.dumps(result) + "\n")
        settles = [f"{x['status']} {x['body'].get('errorReason') or ('success' if x['body'].get('success') else '')} {(x['body'].get('transaction') or '')[:12]}"
                   for x in result["facilitator_exchanges"] if x["path"].startswith("/settle") and isinstance(x["body"], dict)]
        log(f"{name}: {verdict}; client saw {[(g['status'], (g['payment_response'] or {}).get('errorReason') or ('success' if (g['payment_response'] or {}).get('success') else None), ((g['payment_response'] or {}).get('transaction') or '')[:12]) for g in graded]}; "
            f"/settle answers {settles}; authorizations used {paid} of {len(nonces)}; seller +{result['seller_usdc_delta']}, buyer {result['buyer_usdc_delta']}")


if __name__ == "__main__":
    main()
