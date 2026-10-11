"""Fault-injecting JSON-RPC proxy for the x402-rs #136 reproduction.

Adapted from the OpenZeppelin Relayer #843 proxy (proxy843.py in https://github.com/zachsplat/relayer-843-repro): same
forwarding server and control endpoint, different faults. It forwards JSON-RPC to anvil and,
once armed, makes the receipt lookups for the next broadcast transaction fail for a window,
while the transaction itself is forwarded and lands.

POST /control, JSON, every field optional; each call replaces the whole fault setup:
  receipt_fault  "503" | "null" | "off"   what eth_getTransactionReceipt gets inside the window.
                 "503" is HTTP 503 with the body a load balancer with no healthy backend sends
                 (JSON-RPC error -32011), the response quoted in x402-rs #136. "null" is a
                 well-formed result of null, as a lagging backend answers.
  scope          "receipt" (default): only eth_getTransactionReceipt for that transaction fails.
                 "all": every call except eth_sendRawTransaction fails, a whole-provider outage.
  window         seconds the window stays open after the broadcast (default 30).
  send_fault     "503" | "off"   the next eth_sendRawTransaction gets HTTP 503 and is not
                 forwarded: nothing is broadcast (the pre-send control case).
The window opens on the first eth_sendRawTransaction that anvil accepts after /control.
GET /stats returns counters, GET /events the sends and injected faults with timestamps.
"""
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("UPSTREAM", "http://anvil:8545")
LOG = os.environ.get("PROXY_LOG", "/logs/proxy.log")
NO_BACKEND = {"code": -32011, "message": "no backend is currently healthy to serve traffic"}

lock = threading.Lock()
state = {}
stats = {}
events = []


def reset(config=None):
    config = config or {}
    state.clear()
    state.update({
        "receipt_fault": config.get("receipt_fault", "off"),
        "scope": config.get("scope", "receipt"),
        "window": float(config.get("window", 30)),
        "send_fault": config.get("send_fault", "off"),
        "armed": config.get("receipt_fault", "off") != "off",
        "target_tx": None,
        "window_until": 0.0,
    })


def stamp(t=None):
    t = time.time() if t is None else t
    return time.strftime("%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"


def log(message):
    line = f"{stamp()} {message}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def count(key):
    stats[key] = stats.get(key, 0) + 1


def record(kind, **fields):
    entry = {"t": time.time(), "at": stamp(), "kind": kind, **fields}
    events.append(entry)
    return entry


def forward(body: bytes) -> bytes:
    request = urllib.request.Request(UPSTREAM, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


class Http503(Exception):
    def __init__(self, request_id):
        self.request_id = request_id


def handle_one(obj):
    method = obj.get("method")
    params = obj.get("params") or []
    now = time.time()
    with lock:
        count(f"calls:{method}")
        in_window = now < state["window_until"]
        if method == "eth_sendRawTransaction" and state["send_fault"] == "503":
            state["send_fault"] = "off"
            count("faults:send_503")
            record("fault", method=method, fault="503", note="not forwarded, nothing broadcast")
            log("fault: eth_sendRawTransaction -> HTTP 503, not forwarded (nothing broadcast)")
            raise Http503(obj.get("id"))
        if in_window and state["scope"] == "all" and method != "eth_sendRawTransaction":
            count("faults:all_503")
            record("fault", method=method, fault="503", scope="all")
            raise Http503(obj.get("id"))
        if in_window and method == "eth_getTransactionReceipt" and params and params[0] == state["target_tx"]:
            fault = state["receipt_fault"]
            count(f"faults:receipt_{fault}")
            record("fault", method=method, fault=fault, tx=params[0])
            log(f"fault: eth_getTransactionReceipt({params[0][:12]}...) -> {'HTTP 503' if fault == '503' else 'result null'}")
            if fault == "503":
                raise Http503(obj.get("id"))
            return {"jsonrpc": "2.0", "id": obj.get("id"), "result": None}
    response = json.loads(forward(json.dumps(obj).encode()))
    if method == "eth_sendRawTransaction":
        with lock:
            if "result" in response:
                count("sends:accepted")
                tx = response["result"]
                entry = record("send", tx=tx)
                if state["armed"]:
                    state["armed"] = False
                    state["target_tx"] = tx
                    state["window_until"] = entry["t"] + state["window"]
                    record("window_open", tx=tx, until=stamp(state["window_until"]), scope=state["scope"], fault=state["receipt_fault"])
                    log(f"broadcast {tx} accepted by anvil; {state['scope']} fault '{state['receipt_fault']}' for {state['window']:g} s, until {stamp(state['window_until'])}")
                else:
                    log(f"broadcast {tx} accepted by anvil; no fault armed")
            else:
                count("sends:rejected")
                record("send_rejected", error=response.get("error"))
                log(f"broadcast rejected by anvil: {response.get('error')}")
    return response


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        with lock:
            if self.path.startswith("/events"):
                body = json.dumps(events)
            else:
                body = json.dumps({**stats, "state": dict(state), "window_open_now": time.time() < state["window_until"]})
        self.reply(200, body.encode())

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/control"):
            config = json.loads(body or b"{}")
            with lock:
                reset(config)
                record("control", **config)
            log(f"control: {json.dumps(config, sort_keys=True)}")
            self.reply(200, b'{"ok":true}')
            return
        try:
            obj = json.loads(body)
            out = [handle_one(o) for o in obj] if isinstance(obj, list) else handle_one(obj)
            self.reply(200, json.dumps(out).encode())
        except Http503 as e:
            payload = {"jsonrpc": "2.0", "error": NO_BACKEND, "id": e.request_id}
            self.reply(503, (json.dumps(payload, separators=(",", ":")) + "\n").encode())
        except Exception as e:  # anything else is a proxy bug: say so in the log and the reply
            log(f"proxy error: {e!r}")
            self.reply(200, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": f"proxy: {e}"}}).encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    reset()
    log(f"fault proxy up: upstream {UPSTREAM}, no fault armed")
    ThreadingHTTPServer(("0.0.0.0", 8546), Handler).serve_forever()
