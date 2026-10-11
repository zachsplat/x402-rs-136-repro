"""Tables of the settlement_pending runs, from each run directory's pending-results.jsonl.

  python summarize_pending.py <run dir> [<run dir> ...]  > ../summary.md

Live runs (Base Sepolia) get sepolia.basescan.org links for every settlement transaction.
"""
import json
import os
import sys


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

    if any(os.path.basename(os.path.normpath(d)) == "fork-fix136-20261011T213329Z" for d in sys.argv[1:]):
        print("\nNote: in fork-fix136-20261011T213329Z the receipt-503-15s row also lists the control's"
              " `200 success` (0x89e1cf10...): that run filtered the server log by the second, and both settles"
              " fell in the same second. The fix (millisecond filter) came before every later run.")


if __name__ == "__main__":
    main()
