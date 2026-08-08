"""Real-time web mirror for the Cercus dashboard.

FastAPI + uvicorn server that runs inside a dedicated daemon
``multiprocessing.Process`` so a web client can never block or crash the main
experiment. The dashboard pushes FullState dicts through a single ``mp.Queue``;
this process drains it non-blockingly and broadcasts the latest snapshot to
every connected browser at ~20 Hz over ``/ws/full_state``. Static files are
served on the same port from ``src/core/static/``.

Dependencies (fastapi, uvicorn, websockets) were added to requirements.txt with
explicit human approval — BOUNDARY.md's dependency lock permits that.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import queue
import socket
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
import uvicorn

DEFAULT_PORT = 8000
_SHUTDOWN_KEY = "__shutdown__"

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _json_default(o: Any) -> Any:
    if isinstance(o, (tuple, set)):
        return list(o)
    if hasattr(o, "tolist"):
        return o.tolist()
    return str(o)


def _sanitize_nonfinite(obj: Any) -> Any:
    """Recursively replace non-finite floats (NaN/±Inf) so the browser's
    JSON.parse can never reject the frame (user-entered 'inf'/'nan' reach this)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else 0.0
    if isinstance(obj, dict):
        return {k: _sanitize_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_nonfinite(v) for v in obj]
    if hasattr(obj, "item"):  # numpy scalar (np.float32 is not a float subclass)
        try:
            return _sanitize_nonfinite(float(obj))
        except (TypeError, ValueError):
            return obj
    return obj


def _dumps(state: Any) -> str:
    try:
        return json.dumps(state, default=_json_default, allow_nan=False)
    except ValueError:
        # non-finite float present — sanitize and retry (rare path)
        return json.dumps(_sanitize_nonfinite(state), default=_json_default, allow_nan=False)


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


class _Manager:
    """Tracks connected WebSocket clients and the latest FullState snapshot."""

    def __init__(self) -> None:
        self.clients: set = set()
        self.latest: Dict[str, Any] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, text: str) -> None:
        for ws in list(self.clients):
            try:
                # Timeout so one slow client can't stall the ~20 Hz pump for all.
                await asyncio.wait_for(ws.send_text(text), timeout=1.0)
            except Exception:
                self.clients.discard(ws)
                try:
                    # ws.close() is also a backpressured ASGI send that awaits
                    # writable — bound it too, else a dead client hangs the pump
                    # on the cleanup path. The browser's onclose then reconnects.
                    await asyncio.wait_for(ws.close(), timeout=1.0)
                except Exception:
                    pass


async def _pump_loop(state_q: "queue.Queue", manager: _Manager, holder: dict) -> None:
    """Non-blockingly drain the state queue, then broadcast the latest snapshot
    to every client at ~20 Hz. A {'__shutdown__': True} frame stops the server."""
    def _stop() -> None:
        server = holder.get("server")
        if server is not None:
            server.should_exit = True

    while True:
        while True:
            try:
                item = state_q.get_nowait()
            except queue.Empty:
                break
            except (ValueError, OSError, EOFError):  # queue/feeder gone
                _stop()
                return
            if isinstance(item, dict) and item.get(_SHUTDOWN_KEY):
                _stop()
                return
            manager.latest = item

        if manager.clients and manager.latest:
            try:
                await manager.broadcast(_dumps(manager.latest))
            except Exception:
                pass
        await asyncio.sleep(0.05)


def _build_app(state_q: "queue.Queue", holder: dict) -> FastAPI:
    manager = _Manager()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(_pump_loop(state_q, manager, holder))
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="Cercus Web Telemetry", lifespan=lifespan)

    @app.websocket("/ws/full_state")
    async def ws_full_state(ws: WebSocket):
        await manager.connect(ws)
        try:
            if manager.latest:
                await ws.send_text(_dumps(manager.latest))  # instant first paint
            while True:
                try:
                    # Idle browsers send nothing — the timeout is only a probe
                    # to reap a handler whose connection the pump already dropped
                    # for backpressure (otherwise the half-open task leaks).
                    await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                except asyncio.TimeoutError:
                    if ws not in manager.clients:
                        return
        except Exception:
            pass  # disconnect, send failure, or any other client error
        finally:
            manager.disconnect(ws)

    # Static files last so the websocket route matches first.
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
    return app


def _make_server(
    state_q: "queue.Queue",
    holder: dict,
    host: str,
    port: int,
    log_level: str = "warning",
) -> uvicorn.Server:
    """Build the uvicorn server (shared by the daemon entry and the self-check)."""
    app = _build_app(state_q, holder)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        lifespan="on",
        ws="websockets-sansio",
    )
    server = uvicorn.Server(config)
    holder["server"] = server
    return server


def web_telemetry_entry(state_q: "queue.Queue", port: int = DEFAULT_PORT) -> None:
    """mp.Process target: run the FastAPI mirror until told to shut down."""
    holder: dict = {}
    try:
        _make_server(state_q, holder, "0.0.0.0", port).run()
    except Exception:
        # The web mirror is best-effort; it must never affect the experiment.
        pass


# ---------------------------------------------------------------------------
# Self-check: run the app in-thread, push synthetic states, and verify a
# WebSocket client receives valid full_state JSON (and GET / serves HTML).
# ---------------------------------------------------------------------------


def _demo() -> int:
    import threading
    import time

    state_q: "queue.Queue" = queue.Queue()
    holder: dict = {}
    port = find_free_port(8326)
    server = _make_server(state_q, holder, "127.0.0.1", port, "error")
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"

    for i in range(10):
        state_q.put(
            {
                "ts": time.time(),
                "seq": i,
                "config": {"Paradigm": "Looming", "Pattern": "demo"},
                "live": {"phase": f"trial-{i}", "hardware_state": {"dx": i}},
            }
        )
        time.sleep(0.03)

    import urllib.request

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
        assert r.status == 200 and b"<html" in r.read().lower(), "GET / did not serve HTML"

    import websockets

    async def _client() -> bool:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/full_state") as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            obj = json.loads(msg)
            return "config" in obj and "live" in obj and "seq" in obj

    ok = asyncio.run(_client())
    state_q.put({_SHUTDOWN_KEY: True})
    thread.join(timeout=3)
    assert ok, "demo failed: no valid full_state JSON received over WebSocket"
    print(f"OK: FastAPI mirror served / and WS full_state on port {port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
