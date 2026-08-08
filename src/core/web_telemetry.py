"""Real-time web mirror for the Cercus dashboard.

Pure-stdlib HTTP + WebSocket server that runs inside a dedicated daemon
``multiprocessing.Process`` so a web client can never block or crash the main
experiment. The dashboard pushes FullState dicts through a single ``mp.Queue``;
this process coalesces them and broadcasts the latest snapshot to every
connected browser at ~20 Hz over ``/ws/full_state``. Static files are served on
the same port from ``src/core/static/``.

Why stdlib only: BOUNDARY.md locks ``requirements.txt``, so FastAPI/uvicorn are
off-limits without human approval. A push-only WebSocket server is ~150 lines.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import queue
import socket
import struct
import threading
import time
from typing import Any, Dict, List, Optional

DEFAULT_PORT = 8000

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_SHUTDOWN_KEY = "__shutdown__"
_READ_TIMEOUT = object()

_STATIC_INDEX = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "index.html"
)


def _json_default(o: Any) -> Any:
    if isinstance(o, (tuple, set)):
        return list(o)
    if hasattr(o, "tolist"):
        return o.tolist()
    return str(o)


def _sanitize_nonfinite(obj: Any) -> Any:
    """Recursively replace non-finite floats (NaN/±Inf) so JSON.parse in the
    browser can never reject the frame (user-entered 'inf'/'nan' reach this)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else 0.0
    if isinstance(obj, dict):
        return {k: _sanitize_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_nonfinite(v) for v in obj]
    return obj


def _dumps(state: Any) -> bytes:
    try:
        return json.dumps(state, default=_json_default, allow_nan=False).encode("utf-8")
    except ValueError:
        # non-finite float present — sanitize and retry (rare path)
        return json.dumps(
            _sanitize_nonfinite(state), default=_json_default, allow_nan=False
        ).encode("utf-8")


def find_free_port(preferred: int = DEFAULT_PORT, tries: int = 50) -> int:
    """Find the lowest free port at/above `preferred`; 0 if none free."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return 0


def _ws_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    """Encode a server->client WebSocket frame (never masked)."""
    n = len(payload)
    if n < 126:
        head = bytes([0x80 | opcode, n])
    elif n < 65536:
        head = bytes([0x80 | opcode, 126]) + struct.pack(">H", n)
    else:
        head = bytes([0x80 | opcode, 127]) + struct.pack(">Q", n)
    return head + payload


def _recv_exact(conn: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def _read_frame(conn: socket.socket):
    """Read one client->server frame. Returns (opcode, payload), None on EOF,
    or _READ_TIMEOUT when the socket timed out without a complete frame."""
    try:
        h = _recv_exact(conn, 2)
        if h is None:
            return None
        b0, b1 = h[0], h[1]
        length = b1 & 0x7F
        if length == 126:
            ext = _recv_exact(conn, 2)
            if ext is None:
                return None
            length = struct.unpack(">H", ext)[0]
        elif length == 127:
            ext = _recv_exact(conn, 8)
            if ext is None:
                return None
            length = struct.unpack(">Q", ext)[0]
        if b1 & 0x80:  # masked
            mask = _recv_exact(conn, 4)
            payload = _recv_exact(conn, length)
            if mask is None or payload is None:
                return None
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        else:
            payload = _recv_exact(conn, length)
            if payload is None:
                return None
        return (b0 & 0x0F, payload)
    except socket.timeout:
        return _READ_TIMEOUT


def _read_headers(conn: socket.socket) -> Optional[List[str]]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        data += chunk
        if len(data) > 65536:
            return None
    return data.decode("latin-1").split("\r\n")


def _find_header(lines: List[str], name: str) -> Optional[str]:
    prefix = name.lower() + ":"
    for line in lines[1:]:
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def _is_ws_upgrade(lines: List[str]) -> bool:
    if not lines or not lines[0].upper().startswith("GET "):
        return False
    upgrade = _find_header(lines, "upgrade")
    return bool(upgrade and "websocket" in upgrade.lower())


def _ws_accept_key(key: str) -> str:
    digest = hashlib.sha1((key.strip() + _WS_GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def local_web_url(port: int = DEFAULT_PORT) -> str:
    """Best-effort LAN URL for the mirror; falls back to 127.0.0.1."""
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # binds a route; no packets are sent
            ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass
    return f"http://{ip}:{port}"


class _Client:
    __slots__ = ("conn", "lock")

    def __init__(self, conn: socket.socket):
        self.conn = conn
        self.lock = threading.Lock()

    def send(self, data: bytes):
        with self.lock:
            self.conn.sendall(data)


class _WebTelemetryServer:
    def __init__(self, state_q: "queue.Queue", port: int = DEFAULT_PORT):
        self.state_q = state_q
        self.port = port
        self._lock = threading.Lock()
        self._clients: set = set()
        self._latest: Dict[str, Any] = {}
        self._serialized: Optional[bytes] = None
        self._running = True
        try:
            with open(_STATIC_INDEX, "rb") as f:
                self._index_html = f.read()
        except OSError:
            self._index_html = b"<h1>Cercus web mirror: static/index.html missing</h1>"

    # -- producers ---------------------------------------------------------

    def _pump_loop(self):
        while self._running:
            drained = False
            try:
                while True:
                    item = self.state_q.get_nowait()
                    if isinstance(item, dict) and item.get(_SHUTDOWN_KEY):
                        self._running = False
                        return
                    with self._lock:
                        self._latest = item
                        self._serialized = None
                    drained = True
            except queue.Empty:
                pass
            except (ValueError, OSError, EOFError):
                self._running = False
                return
            time.sleep(0.005 if drained else 0.02)

    def _broadcast_loop(self):
        while self._running:
            with self._lock:
                if self._serialized is None and self._latest:
                    self._serialized = _dumps(self._latest)
                payload = self._serialized
                clients = list(self._clients)
            if payload:
                frame = _ws_frame(payload)
                for client in clients:
                    try:
                        client.send(frame)
                    except OSError:
                        self._drop(client)
            time.sleep(0.05)  # ~20 Hz

    # -- connection handling ----------------------------------------------

    def _drop(self, client: _Client):
        with self._lock:
            self._clients.discard(client)
        try:
            client.conn.close()
        except OSError:
            pass

    def _handle_connection(self, conn: socket.socket):
        conn.settimeout(2.0)
        try:
            lines = _read_headers(conn)
            if not lines or not lines[0]:
                return
            if _is_ws_upgrade(lines):
                key = _find_header(lines, "sec-websocket-key")
                if not key:
                    return
                conn.sendall(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {_ws_accept_key(key)}\r\n\r\n"
                    ).encode("ascii")
                )
                client = _Client(conn)
                with self._lock:
                    self._clients.add(client)
                self._read_loop(client)
            else:
                self._serve_http(conn, lines)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _read_loop(self, client: _Client):
        try:
            while self._running:
                frame = _read_frame(client.conn)
                if frame is None:
                    return
                if frame is _READ_TIMEOUT:
                    continue
                opcode, payload = frame
                if opcode == 0x8:  # close -> echo and drop
                    try:
                        client.send(_ws_frame(b"", opcode=0x8))
                    except OSError:
                        pass
                    return
                if opcode == 0x9:  # ping -> pong
                    try:
                        client.send(_ws_frame(payload or b"", opcode=0xA))
                    except OSError:
                        return
                # text/binary/continuation frames are ignored (push-only server)
        except OSError:
            pass
        finally:
            self._drop(client)

    def _serve_http(self, conn: socket.socket, lines: List[str]):
        parts = lines[0].split()
        if len(parts) < 2:
            return
        path = parts[1].split("?", 1)[0]
        if path in ("/", "/index.html"):
            conn.sendall(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/html; charset=utf-8\r\n"
                b"Cache-Control: no-cache\r\n"
                + f"Content-Length: {len(self._index_html)}\r\n".encode("ascii")
                + b"Connection: close\r\n\r\n"
                + self._index_html
            )
        elif path == "/favicon.ico":
            conn.sendall(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        else:
            conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")

    # -- entry --------------------------------------------------------------

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", self.port))
        except OSError:
            # Port was taken between find_free_port and here (rare race) — never
            # crash the web process over it; fall back to an ephemeral port.
            srv.bind(("0.0.0.0", 0))
            self.port = srv.getsockname()[1]
        srv.listen(16)
        srv.settimeout(1.0)
        threading.Thread(target=self._pump_loop, daemon=True).start()
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        try:
            while self._running:
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(
                    target=self._handle_connection, args=(conn,), daemon=True
                ).start()
        finally:
            self._running = False
            srv.close()
            with self._lock:
                for client in list(self._clients):
                    try:
                        client.conn.close()
                    except OSError:
                        pass


def web_telemetry_entry(state_q: "queue.Queue", port: int = DEFAULT_PORT) -> None:
    """mp.Process target: run the mirror server until told to shut down."""
    _WebTelemetryServer(state_q, port).run()


# ---------------------------------------------------------------------------
# Self-check: run the server in-thread, push synthetic states, and verify a
# raw-socket WebSocket client receives valid full_state JSON.
# ---------------------------------------------------------------------------


class _BufReader:
    """Adapter so _read_frame works against a socket.makefile buffer, which
    preserves any frame bytes that arrived inside the handshake read."""

    def __init__(self, f):
        self.f = f

    def recv(self, n: int) -> bytes:
        try:
            return self.f.read(n)
        except socket.timeout:
            raise


def _demo() -> int:
    q: "queue.Queue" = queue.Queue()
    port = 8321
    server = _WebTelemetryServer(q, port)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.3)

    for i in range(10):
        q.put(
            {
                "ts": time.time(),
                "seq": i,
                "config": {"Paradigm": "Looming", "Pattern": "demo"},
                "live": {"phase": f"trial-{i}", "hardware_state": {"dx": i}},
            }
        )
        time.sleep(0.05)

    conn = socket.create_connection(("127.0.0.1", port), timeout=3.0)
    key = base64.b64encode(b"demo-key").decode("ascii")
    conn.sendall(
        (
            "GET /ws/full_state HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
    )
    f = conn.makefile("rb")
    status = f.readline().decode("latin-1").strip()
    assert "101" in status, status
    while True:
        line = f.readline()
        if line in (b"\r\n", b"\n", b""):
            break

    conn.settimeout(0.5)
    reader = _BufReader(f)
    ok = False
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        frame = _read_frame(reader)
        if frame is None:
            break
        if frame is _READ_TIMEOUT:
            continue
        opcode, payload = frame
        if opcode == 0x1:
            obj = json.loads(payload.decode("utf-8"))
            if "config" in obj and "live" in obj and "seq" in obj:
                ok = True
                break
    f.close()
    conn.close()

    q.put({_SHUTDOWN_KEY: True})
    thread.join(timeout=3.0)
    assert ok, "demo failed: no valid full_state JSON received over WebSocket"
    print(f"OK: full_state JSON received over WebSocket on port {port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
