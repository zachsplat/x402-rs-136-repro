"""Tables of the settlement_pending runs, from each run directory's pending-results.jsonl.

  python summarize_pending.py <run dir> [<run dir> ...]  > ../summary.md

Live runs (Base Sepolia) get sepolia.basescan.org links for every settlement transaction.
"""
import json
import os
import sys
from datetime import datetime


def short(tx):
    return f"{tx[:10]}...{tx[-4:]}" if tx else ""


def main():
    for run_dir in sys.argv[1:]:
        path = os.path.join(run_dir, "pending-results.jsonl")
        if not os.path.exists(path):
            continue
        live = "/live/" in os.path.abspath(run_dir)
        image = open(os.path.join(run_dir, "image.txt")).read().splitlines()
        print(f"\n### {os.path.basename(os.path.normpath(run_dir))} ({'Base Sepolia' if live else 'anvil fork of Base Sepolia'})\n")
        print("`" + "`, `".join(line for line in image if line.startswith(("image:", "labels:", "facilitator config:"))) + "`\n")
        print("| Scenario | Client saw (HTTP, PAYMENT-RESPONSE) | Client waited (s) | /settle answers, in order | Paid | Answers | Verdict | Settlement transactions |")
        print("|---|---|---|---|---|---|---|---|")
        for line in open(path):
            r = json.loads(line)
            saw = "; ".join(
                f"{c['status']} {((c['payment_response'] or {}).get('errorReason') or ('success' if (c['payment_response'] or {}).get('success') else '-'))}"
                f" tx={'yes' if (c['payment_response'] or {}).get('transaction') else 'empty'}"
                for c in r["calls"])
            settles = ", ".join(
                f"{x['status']} {x['body'].get('errorReason') or ('success' if x['body'].get('success') else '')}".strip()
                for x in r["facilitator_exchanges"] if x["path"].startswith("/settle") and isinstance(x["body"], dict))
            txs = [t for ts in r["settlement_txs"].values() for t in ts]
            if live:
                links = ", ".join(f"[{short(t)}](https://sepolia.basescan.org/tx/{t})" for t in txs)
            else:
                links = ", ".join(f"`{short(t)}`" for t in txs)
            waited = ", ".join(f"{c['ms'] / 1000:.1f}" for c in r["calls"])
            print(f"| {r['scenario']} | {saw} | {waited} | {settles} | {r['authorizations_used']} x, seller +{r['seller_usdc_delta'] / 1e6:g} USDC "
                  f"| {r['answers']} | **{r['verdict']}** | {links} |")
        for line in open(path):
            r = json.loads(line)
            for restart in r.get("restarts", []):
                print(f"\n{r['scenario']}: the facilitator was restarted after its 202 and answered again {restart['seconds']} s later.")
            if any(c.get("copy", 1) > 1 for c in r["calls"]):
                sent = ", ".join(f"copy {c['copy']} at {(c.get('sent_after_ms') or 0) / 1000:g} s" for c in r["calls"])
                times = [datetime.fromisoformat(x["t"].replace("Z", "+00:00")) for x in r["facilitator_exchanges"]]
                steps = []
                for x, t in zip(r["facilitator_exchanges"], times):
                    body = x["body"] if isinstance(x["body"], dict) else {}
                    answer = ("valid" if body.get("isValid") else body.get("invalidReason") or "invalid") if x["path"].startswith("/verify") else (
                        "success" if body.get("success") else body.get("errorReason") or "")
                    tx = f" {short(body['transaction'])}" if body.get("transaction") else ""
                    steps.append(f"{x['path']} {x['status']} {answer}{tx} (+{(t - times[0]).total_seconds():.1f} s)")
                print(f"\n{r['scenario']}: {sent}; the resource server's exchanges with the facilitator, in the order answered (time of the answer): {'; '.join(steps)}.")
            for replay in r.get("replays", []):
                body = replay["body"] if isinstance(replay["body"], dict) else {}
                answer = ("success" if body.get("success") else body.get("errorReason") or body.get("invalidReason")
                          or ("valid" if body.get("isValid") else "") or str(replay["body"])[:80])
                print(f"\n{r['scenario']}: the payment's {replay['path']} sent again: {replay['status']} {answer}"
                      f"{' ' + short(body['transaction']) if body.get('transaction') else ''}.")

    if any(os.path.basename(os.path.normpath(d)) == "fork-fix136-20261011T213329Z" for d in sys.argv[1:]):
        print("\nNote: in fork-fix136-20261011T213329Z the receipt-503-15s row also lists the control's"
              " `200 success` (0x89e1cf10...): that run filtered the server log by the second, and both settles"
              " fell in the same second. The fix (millisecond filter) came before every later run.")


if __name__ == "__main__":
    main()
