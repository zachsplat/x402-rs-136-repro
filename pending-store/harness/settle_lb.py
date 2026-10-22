"""HTTP proxy between the resource server and the facilitator, for the restart rows.

Forwards every request to UPSTREAM (the facilitator) and keeps each /settle and /verify
exchange (request body, status, response body) for GET /events. Once armed, it restarts the
facilitator container when a /settle answers 202 settlement_pending, before it passes that
answer on: the resource server's retry, which follows the 202 at once, then reaches a new
facilitator process whose pending-settlement store is empty, as after a crash or a deploy, or
as when the retry is sent to another instance.

POST /control, JSON, every field optional; each call replaces the setup:
  restart_on_pending  true: restart the facilitator on the next 202 from /settle (once).
The restart goes through the Docker Engine API on DOCKER_SOCKET (the container named in
FACILITATOR_CONTAINER, killed at once and started again), then waits until UPSTREAM answers
/supported. GET /events returns the exchanges and restarts with timestamps.
"""
import http.client
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("UPSTREAM", "http://facilitator:8080").rstrip("/")
CONTAINER = os.environ.get("FACILITATOR_CONTAINER", "")
DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
LOG = os.environ.get("LB_LOG", "/logs/lb.log")

lock = threading.Lock()
state = {"restart_on_pending": False}
events = []


def stamp(t=None):
    t = time.time() if t is None else t
    return time.strftime("%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"


def log(message):
    line = f"{stamp()} {message}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def record(kind, **fields):
    with lock:
        events.append({"t": time.time(), "kind": kind, **fields})


class DockerSocket(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=60)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(60)
        self.sock.connect(DOCKER_SOCKET)


def restart_facilitator():
    t0 = time.time()
    conn = DockerSocket()
    conn.request("POST", f"/containers/{CONTAINER}/restart?t=0")
    status = conn.getresponse().status
    conn.close()
    up = None
    for _ in range(120):
        try:
            with urllib.request.urlopen(UPSTREAM + "/supported", timeout=3) as r:
                if r.status == 200:
                    up = time.time()
                    break
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.25)
    record("restart", container=CONTAINER, docker_status=status, seconds=round((up or time.time()) - t0, 2), up=up is not None)
    log(f"restarted {CONTAINER} (docker {status}); facilitator {'up' if up else 'NOT up'} after {(up or time.time()) - t0:.2f} s")


def forward(method, path, body, headers):
    request = urllib.request.Request(UPSTREAM + path, data=body if method == "POST" else None, method=method,
                                     headers={k: v for k, v in headers.items() if k.lower() in ("content-type", "accept")})
    try:
        with urllib.request.urlopen(request, timeout=180) as r:
            return r.status, r.headers.get("Content-Type", "application/json"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "application/json"), e.read()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def reply(self, code, content_type, data: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if self.path.startswith("/control") and method == "POST":
            config = json.loads(body or b"{}")
            with lock:
                state["restart_on_pending"] = bool(config.get("restart_on_pending", False))
            log(f"control {config}")
            return self.reply(200, "application/json", json.dumps(state).encode())
        if self.path.startswith("/events") and method == "GET":
            with lock:
                data = json.dumps(events).encode()
            return self.reply(200, "application/json", data)
        t0 = time.time()
        status, content_type, data = forward(method, self.path, body, self.headers)
        exchange = self.path.startswith(("/settle", "/verify"))
        restart = False
        if exchange:
            try:
                answer = json.loads(data)
            except ValueError:
                answer = data.decode(errors="replace")[:2000]
            record("exchange", path=self.path, status=status, ms=int((time.time() - t0) * 1000),
                   request=json.loads(body) if body else None, response=answer)
            log(f"{method} {self.path} -> {status} {data[:200].decode(errors='replace')}")
            with lock:
                if self.path.startswith("/settle") and status == 202 and state["restart_on_pending"]:
                    state["restart_on_pending"] = False
                    restart = True
        if restart:
            restart_facilitator()
        return self.reply(status, content_type, data)

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    log(f"settle lb on :8080 -> {UPSTREAM}, restarts {CONTAINER or '(no container set)'}")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
