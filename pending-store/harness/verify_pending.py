"""Check the settlement transactions of a live pending-store run against Base Sepolia, after the fact.

For each scenario in <run dir>/pending-results.jsonl, takes the transactions that used each
authorization the client signed (found through the AuthorizationUsed logs) and fetches their
receipts from two public endpoints. Checks, per transaction: status 1, sent by the facilitator's
signer, a USDC Transfer from the buyer to the seller of exactly the signed value, and
AuthorizationUsed(buyer, nonce) for the nonce the client signed. Addresses come from the run's
own files: the signer from supported.json, the buyer and the signed values from the client
records, the seller from server.log. Writes verified.jsonl and verified.md in the run directory.

  python verify_pending.py <live run dir> [<live run dir> ...]
"""
import json
import os
import sys
import time

import httpx
from eth_utils import keccak

RPCS = os.environ.get("VERIFY_RPCS", "https://sepolia.base.org,https://base-sepolia-rpc.publicnode.com").split(",")
NETWORK = "eip155:84532"
USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
TRANSFER = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
AUTH_USED = "0x" + keccak(text="AuthorizationUsed(address,bytes32)").hex()


def receipt(url, tx):
    for _ in range(5):
        try:
            reply = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx]},
                               timeout=20).json()
            if reply.get("result"):
                return reply["result"]
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(2)
    return None


def topic_address(topic):
    return "0x" + topic[-40:].lower()


def jsonl(path):
    return [json.loads(line) for line in open(path) if line.strip()]


def check(run_dir):
    signer = json.load(open(os.path.join(run_dir, "supported.json")))["signers"][NETWORK][0].lower()
    seller = next(e["pay_to"] for e in jsonl(os.path.join(run_dir, "server.log")) if e.get("kind") == "start").lower()
    rows, buyer = [], ""
    for result in jsonl(os.path.join(run_dir, "pending-results.jsonl")):
        client = jsonl(os.path.join(run_dir, f"client-{result['label']}-{result['scenario']}.jsonl"))
        buyer = next(e["buyer"] for e in client if e.get("kind") == "start").lower()
        values = {p["nonce"]: int(p["value"]) for e in client if e.get("kind") == "call" for p in e.get("payments", [])}
        for nonce, txs in result["settlement_txs"].items():
            for tx in txs:
                seen = {url: receipt(url, tx) for url in RPCS}
                r = next((x for x in seen.values() if x), None) or {}
                logs = [l for l in r.get("logs", []) if l["address"].lower() == USDC]
                row = {
                    "scenario": result["scenario"], "nonce": nonce, "transaction": tx, "signed_value": values.get(nonce),
                    "block": int(r["blockNumber"], 16) if r else None,
                    "status": int(r["status"], 16) if r else None,
                    "from_signer": bool(r) and r["from"].lower() == signer,
                    "transfer_ok": any(l["topics"][0] == TRANSFER and topic_address(l["topics"][1]) == buyer
                                       and topic_address(l["topics"][2]) == seller and int(l["data"], 16) == values.get(nonce)
                                       for l in logs),
                    "authorization_used_ok": any(l["topics"][0] == AUTH_USED and topic_address(l["topics"][1]) == buyer
                                                 and l["topics"][2].lower() == nonce.lower() for l in logs),
                    "endpoints": {url: (x and {"status": int(x["status"], 16), "block_hash": x["blockHash"]}) for url, x in seen.items()},
                }
                answers = list(row["endpoints"].values())
                row["endpoints_agree"] = all(answers) and all(a == answers[0] for a in answers)
                row["verified"] = (row["status"] == 1 and row["from_signer"] and row["transfer_ok"]
                                   and row["authorization_used_ok"] and row["endpoints_agree"])
                rows.append(row)
    read_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(run_dir, "verified.jsonl"), "w") as f:
        for row in rows:
            f.write(json.dumps({"read_at": read_at, **row}) + "\n")
    lines = [
        f"Read {read_at} from {' and '.join(RPCS)}. Signer {signer}, buyer {buyer}, seller {seller}.",
        "",
        "| Scenario | Authorization nonce | Settlement transaction | Block | Status | From the signer | Transfer buyer to seller (USDC) | AuthorizationUsed for the nonce | Both endpoints agree | Verified |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        tx = row["transaction"]
        lines.append(f"| {row['scenario']} | `{row['nonce'][:10]}...` | [{tx[:10]}...{tx[-4:]}](https://sepolia.basescan.org/tx/{tx}) "
                     f"| {row['block']} | {row['status']} | {row['from_signer']} | {row['transfer_ok']} ({(row['signed_value'] or 0) / 1e6:g}) "
                     f"| {row['authorization_used_ok']} | {row['endpoints_agree']} | {row['verified']} |")
    open(os.path.join(run_dir, "verified.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n{sum(1 for r in rows if r['verified'])} of {len(rows)} verified")


if __name__ == "__main__":
    for run_dir in sys.argv[1:]:
        check(run_dir)
