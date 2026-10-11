"""Every exchange between the resource server and the facilitator in a run, from its server.log.

  python facilitator_answers.py <run dir> [<run dir> ...]   writes facilitator-answers.md in each
"""
import json
import os
import sys


def answer(body):
    if not isinstance(body, dict):
        return str(body)[:200]
    if "isValid" in body:
        parts = [f"isValid {body['isValid']}"]
        if body.get("invalidReason"):
            parts.append(str(body["invalidReason"]))
        if body.get("payer"):
            parts.append(f"payer {body['payer']}")
        return ", ".join(parts)
    parts = [f"success {body.get('success')}"]
    if body.get("errorReason"):
        parts.append(f"errorReason {body['errorReason']}")
    parts.append(f"transaction {body.get('transaction') or '(empty)'}")
    if body.get("network"):
        parts.append(f"network {body['network']}")
    if body.get("errorMessage"):
        parts.append(f"errorMessage \"{str(body['errorMessage'])[:160]}\"")
    return ", ".join(parts).replace("|", "\\|")


def main():
    for run_dir in sys.argv[1:]:
        lines = ["| Time (UTC) | Facilitator endpoint | HTTP | ms | Answer |", "|---|---|---|---|---|"]
        for line in open(os.path.join(run_dir, "server.log")):
            entry = json.loads(line)
            if entry.get("kind") != "facilitator":
                continue
            status = entry.get("status", f"error: {entry.get('error')}")
            lines.append(f"| {entry['t'][11:23]} | {entry['path']} | {status} | {entry.get('ms')} | {answer(entry.get('body'))} |")
        open(os.path.join(run_dir, "facilitator-answers.md"), "w").write("\n".join(lines) + "\n")
        print(f"{run_dir}: {len(lines) - 2} exchanges")


if __name__ == "__main__":
    main()
