"""Tests for concurrency safety, zero thread leaks, signal handling, and worker death detection."""

import ast
import multiprocessing as mp
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.audit_concurrency import ConcurrencyAuditor, audit_all, audit_thread_leak
from src.core.hardware import MockSerialDaemon
from src.ui.app import _global_poll, controller, state
from src.ui.controller import ExperimentController
import src.workers.calibration_worker as calib_mod
import src.workers.stimulus_worker as stim_mod


def test_static_concurrency_audit_passes() -> None:
    """Verify entire codebase passes static concurrency safety audit with 0 violations."""
    violations = audit_all(ROOT_DIR)
    if violations:
        msg = "\n".join(str(v) for v in violations)
        pytest.fail(f"Concurrency safety violations found:\n{msg}")


def test_hot_path_queue_put_uses_nowait_or_timeout() -> None:
    """Verify all queue.put() calls in hot path files have timeout or use put_nowait."""
    hot_files = [
        ROOT_DIR / "src" / "workers" / "stimulus_worker.py",
        ROOT_DIR / "src" / "workers" / "calibration_worker.py",
        ROOT_DIR / "src" / "core" / "hardware.py",
        ROOT_DIR / "src" / "ui" / "controller.py",
    ]
    for hf in hot_files:
        auditor = ConcurrencyAuditor(str(hf), ROOT_DIR, hf.read_text(encoding="utf-8"))
        violations = auditor.audit()
        put_violations = [v for v in violations if v.category == "queue-put-timeout"]
        assert not put_violations, f"Blocking queue.put found in {hf}: {put_violations}"


def test_signal_handlers_only_set_flags_ast() -> None:
    """Verify signal handlers in worker modules do not contain raise or blocking statements."""
    for mod_path in [
        ROOT_DIR / "src" / "workers" / "stimulus_worker.py",
        ROOT_DIR / "src" / "workers" / "calibration_worker.py",
    ]:
        auditor = ConcurrencyAuditor(str(mod_path), ROOT_DIR, mod_path.read_text(encoding="utf-8"))
        violations = auditor.audit()
        sig_violations = [v for v in violations if v.category == "signal-handler-unsafe"]
        assert not sig_violations, f"Unsafe signal handler in {mod_path}: {sig_violations}"


def test_signal_handlers_behavior() -> None:
    """Verify invoking signal handlers sets the shutdown event without raising exceptions."""
    # Stimulus worker handler
    stim_mod._shutdown_event.clear()
    assert not stim_mod._shutdown_event.is_set()
    stim_mod._term_handler(signal.SIGTERM, None)
    assert stim_mod._shutdown_event.is_set()
    stim_mod._shutdown_event.clear()

    # Calibration worker handler
    calib_mod._shutdown_event.clear()
    assert not calib_mod._shutdown_event.is_set()
    calib_mod._term_handler(signal.SIGINT, None)
    assert calib_mod._shutdown_event.is_set()
    calib_mod._shutdown_event.clear()


def test_thread_leak_100_serial_daemons_sequential() -> None:
    """Spawn, run, and stop 100 SerialDaemons sequentially and verify 0 thread leak."""
    initial_threads = threading.active_count()

    for _ in range(100):
        daemon = MockSerialDaemon()
        daemon.start(time_func=time.perf_counter)
        assert daemon.is_alive()
        time.sleep(0.002)
        items = daemon.drain_queue()
        assert isinstance(items, list)
        daemon.stop()
        assert not daemon.is_alive()

    # Allow daemon thread exit
    time.sleep(0.05)
    assert threading.active_count() <= initial_threads


def test_thread_leak_100_serial_daemons_concurrent() -> None:
    """Spawn 100 SerialDaemons simultaneously, verify streaming, stop all, verify 0 thread leak."""
    initial_threads = threading.active_count()
    daemons: List[MockSerialDaemon] = []

    for _ in range(100):
        d = MockSerialDaemon()
        d.start(time_func=time.perf_counter)
        daemons.append(d)

    time.sleep(0.05)

    for d in daemons:
        items = d.drain_queue()
        assert len(items) > 0
        d.stop()

    time.sleep(0.05)
    assert threading.active_count() <= initial_threads


def test_audit_thread_leak_helper() -> None:
    """Verify audit_thread_leak helper function runs cleanly."""
    ok, msg = audit_thread_leak(spawn_count=20)
    assert ok is True
    assert "0 thread leaks" in msg


def test_worker_death_detection_silent_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _global_poll detects worker death when worker exits without a terminal frame."""
    cleanup_called = False

    def _mock_cleanup() -> None:
        nonlocal cleanup_called
        cleanup_called = True

    controller.terminal_status = None
    controller.terminal_error = ""
    state.worker_died = False
    state.worker_status = "running"
    state.worker_error = ""

    monkeypatch.setattr(controller, "poll_telemetry", lambda: {
        "telemetry": None,
        "verdicts": [],
        "terminal": None,
        "worker_died": True,
    })
    monkeypatch.setattr(controller, "cleanup_worker", _mock_cleanup)

    _global_poll()

    assert cleanup_called is True
    assert state.worker_died is True
    assert controller.terminal_status == "worker_error"
    assert "Worker process exited unexpectedly" in controller.terminal_error
    assert state.worker_status == "worker_error"
    assert "Worker process exited unexpectedly" in state.worker_error


def test_worker_death_detection_done_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _global_poll preserves worker_done status upon clean process termination."""
    cleanup_called = False

    def _mock_cleanup() -> None:
        nonlocal cleanup_called
        cleanup_called = True

    controller.terminal_status = "worker_done"
    controller.terminal_error = ""
    state.worker_died = True
    state.worker_status = "worker_done"
    state.worker_error = ""

    monkeypatch.setattr(controller, "poll_telemetry", lambda: {
        "telemetry": None,
        "verdicts": [],
        "terminal": None,
        "worker_died": True,
    })
    monkeypatch.setattr(controller, "cleanup_worker", _mock_cleanup)

    _global_poll()

    assert cleanup_called is True
    assert controller.terminal_status == "worker_done"
    assert state.worker_status == "worker_done"
    assert state.worker_error == ""


def test_worker_death_detection_abort_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify _global_poll preserves worker_abort status when worker aborts."""
    cleanup_called = False

    def _mock_cleanup() -> None:
        nonlocal cleanup_called
        cleanup_called = True

    controller.terminal_status = "worker_abort"
    controller.terminal_error = "User aborted"
    state.worker_died = True
    state.worker_status = "worker_abort"
    state.worker_error = "User aborted"

    monkeypatch.setattr(controller, "poll_telemetry", lambda: {
        "telemetry": None,
        "verdicts": [],
        "terminal": None,
        "worker_died": True,
    })
    monkeypatch.setattr(controller, "cleanup_worker", _mock_cleanup)

    _global_poll()

    assert cleanup_called is True
    assert controller.terminal_status == "worker_abort"
    assert state.worker_status == "worker_abort"
    assert state.worker_error == "User aborted"


def test_kill_worker_terminates_before_bounded_join() -> None:
    """Verify a live worker is terminated before the bounded join."""
    ctrl = ExperimentController()
    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = True

    ctrl._kill_worker(mock_proc, timeout=0.1)

    mock_proc.terminate.assert_called_once()
    mock_proc.join.assert_called_once_with(timeout=0.1)


def test_controller_stop_experiment_fallback_kill() -> None:
    """Verify controller.stop_experiment falls back to killing worker when queue fails."""
    ctrl = ExperimentController()
    mock_proc = MagicMock()
    mock_proc.is_alive.return_value = True
    ctrl.worker_process = mock_proc

    mock_queue = MagicMock()
    mock_queue.put_nowait.side_effect = queue.Full("Queue is full")
    mock_queue.get_nowait.side_effect = queue.Empty
    ctrl.cmd_queue = mock_queue

    kill_called = False

    def _mock_kill() -> None:
        nonlocal kill_called
        kill_called = True

    ctrl._terminate_worker_nonblocking = _mock_kill
    ctrl.stop_experiment()

    assert kill_called is True


def test_concurrency_auditor_flags_unsafe_signal_handler() -> None:
    """Verify ConcurrencyAuditor detects raising exceptions in signal handlers."""
    unsafe_code = """
import signal

def bad_handler(sig, frame):
    raise SystemExit(1)

def setup():
    signal.signal(signal.SIGTERM, bad_handler)
"""
    auditor = ConcurrencyAuditor("src/workers/dummy.py", ROOT_DIR, unsafe_code)
    violations = auditor.audit()
    assert any(v.category == "signal-handler-unsafe" for v in violations)


def test_concurrency_auditor_flags_blocking_queue_put() -> None:
    """Verify ConcurrencyAuditor detects blocking queue.put() without timeout in hot path."""
    blocking_code = """
import queue

def hot_loop(q):
    q.put({"data": 123})
"""
    auditor = ConcurrencyAuditor("src/workers/stimulus_worker.py", ROOT_DIR, blocking_code)
    violations = auditor.audit()
    assert any(v.category == "queue-put-timeout" for v in violations)
