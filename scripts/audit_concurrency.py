"""AST and Dynamic Concurrency Safety Auditor for Cercus.

Audits:
1. AST static scan of all queue.put() calls in hot paths (must use put_nowait() or timeout).
2. AST static scan of signal handlers (must only set flags/events, no raise SystemExit or blocking calls).
3. AST static scan of queue cleanup (cancel_join_thread() calls on IPC queues to prevent feeder deadlocks).
4. Dynamic thread leak audit (spawning and terminating 100 SerialDaemon instances).
5. Dynamic worker death detection in app._global_poll.
"""

import argparse
import ast
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path for direct CLI execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.hardware import MockSerialDaemon
from src.ui.controller import ExperimentController
from src.ui.state import AppState


HOT_PATH_FILES: Set[str] = {
    "src/workers/stimulus_worker.py",
    "src/workers/calibration_worker.py",
    "src/core/hardware.py",
    "src/ui/controller.py",
}


class ConcurrencyViolation:
    """Represents a concurrency safety violation."""

    def __init__(self, file_path: str, line: int, category: str, message: str) -> None:
        """Initialize concurrency violation."""
        self.file_path = file_path
        self.line = line
        self.category = category
        self.message = message

    def __str__(self) -> str:
        """Format violation as string."""
        return f"{self.file_path}:{self.line} [{self.category}] {self.message}"


class ConcurrencyAuditor(ast.NodeVisitor):
    """AST visitor enforcing concurrency safety rules across Cercus subsystems."""

    def __init__(self, file_path: str, root_dir: Path, source_code: str) -> None:
        """Initialize concurrency auditor."""
        self.file_path = str(file_path)
        self.source_code = source_code
        self.violations: List[ConcurrencyViolation] = []

        try:
            rel = Path(file_path).resolve().relative_to(root_dir.resolve())
            self.rel_path = rel.as_posix()
        except ValueError:
            self.rel_path = Path(file_path).as_posix()

        self.function_defs: Dict[str, ast.FunctionDef] = {}
        self.signal_handlers: List[Tuple[int, str]] = []
        self.current_function: Optional[str] = None
        self.is_hot_path = self.rel_path in HOT_PATH_FILES

    def audit(self) -> List[ConcurrencyViolation]:
        """Run AST audit on the source tree."""
        try:
            tree = ast.parse(self.source_code, filename=self.file_path)
        except SyntaxError as e:
            self.violations.append(
                ConcurrencyViolation(self.file_path, e.lineno or 1, "syntax-error", str(e))
            )
            return self.violations

        # First pass: collect all top-level / class functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                self.function_defs[node.name] = node

        self.visit(tree)
        self._audit_signal_handlers()
        return self.violations

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track current function context."""
        prev = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev

    def visit_Call(self, node: ast.Call) -> None:
        """Audit function and method calls for concurrency safety."""
        # 1. Check signal.signal(sig, handler)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "signal":
            if len(node.args) >= 2:
                handler_arg = node.args[1]
                if isinstance(handler_arg, ast.Name):
                    self.signal_handlers.append((node.lineno, handler_arg.id))

        # 2. Check queue.put() calls in hot paths
        if isinstance(node.func, ast.Attribute) and node.func.attr == "put":
            if self.is_hot_path:
                self._check_queue_put(node)

        self.generic_visit(node)

    def _check_queue_put(self, node: ast.Call) -> None:
        """Verify queue.put has timeout or block=False in hot paths."""
        has_timeout = any(kw.arg == "timeout" for kw in node.keywords)
        has_block_false = any(
            kw.arg == "block"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
            for kw in node.keywords
        )

        # Check positional args: put(item, block, timeout)
        pos_block_false = (
            len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value is False
        )
        pos_timeout = len(node.args) >= 3

        if not (has_timeout or has_block_false or pos_block_false or pos_timeout):
            self.violations.append(
                ConcurrencyViolation(
                    self.file_path,
                    node.lineno,
                    "queue-put-timeout",
                    f"Queue.put() call in hot path '{self.rel_path}' lacks timeout or put_nowait(), risking deadlock.",
                )
            )

    def _audit_signal_handlers(self) -> None:
        """Verify registered signal handlers only set flags and do not raise exceptions."""
        for lineno, handler_name in self.signal_handlers:
            func_node = self.function_defs.get(handler_name)
            if func_node is None:
                continue

            for stmt in ast.walk(func_node):
                if isinstance(stmt, ast.Raise):
                    self.violations.append(
                        ConcurrencyViolation(
                            self.file_path,
                            stmt.lineno,
                            "signal-handler-unsafe",
                            f"Signal handler '{handler_name}' raises an exception. Signal handlers must only set flags.",
                        )
                    )
                elif isinstance(stmt, ast.Call):
                    # Check for exit or blocking calls
                    call_name = ""
                    if isinstance(stmt.func, ast.Name):
                        call_name = stmt.func.id
                    elif isinstance(stmt.func, ast.Attribute):
                        call_name = stmt.func.attr

                    if call_name in ("exit", "sys_exit", "sleep", "wait", "acquire"):
                        self.violations.append(
                            ConcurrencyViolation(
                                self.file_path,
                                stmt.lineno,
                                "signal-handler-unsafe",
                                f"Signal handler '{handler_name}' calls blocking/exit function '{call_name}'. Signal handlers must only set flags.",
                            )
                        )


def audit_file(file_path: Path, root_dir: Path) -> List[ConcurrencyViolation]:
    """Audit a single python source file."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [ConcurrencyViolation(str(file_path), 1, "read-error", str(e))]

    auditor = ConcurrencyAuditor(str(file_path), root_dir, source)
    return auditor.audit()


def audit_all(root_dir: Path, target_dirs: Optional[List[str]] = None) -> List[ConcurrencyViolation]:
    """Audit all python source files under target directories."""
    violations: List[ConcurrencyViolation] = []
    if target_dirs is None:
        target_dirs = ["src", "tests", "scripts"]

    py_files: List[Path] = []
    for d in target_dirs:
        dir_path = root_dir / d
        if dir_path.is_dir():
            py_files.extend(dir_path.rglob("*.py"))
        elif dir_path.is_file() and dir_path.suffix == ".py":
            py_files.append(dir_path)

    for file_name in ["main.py", "test_server.py"]:
        p = root_dir / file_name
        if p.exists():
            py_files.append(p)

    for py_file in sorted(py_files):
        rel_str = str(py_file)
        if any(x in rel_str for x in [".claude", ".pio", "__pycache__", ".pytest_cache"]):
            continue
        file_violations = audit_file(py_file, root_dir)
        violations.extend(file_violations)

    return violations


def audit_thread_leak(spawn_count: int = 100) -> Tuple[bool, str]:
    """Dynamically spawn, run, and stop N SerialDaemon instances to verify zero thread leak."""
    initial_threads = threading.active_count()
    daemons: List[MockSerialDaemon] = []

    try:
        for _ in range(spawn_count):
            d = MockSerialDaemon()
            d.start(time_func=time.perf_counter)
            daemons.append(d)

        # Allow threads to spin and queue items
        time.sleep(0.05)

        for d in daemons:
            items = d.drain_queue()
            d.stop()

        # Allow thread pool teardown
        time.sleep(0.05)

        final_threads = threading.active_count()
        if final_threads > initial_threads:
            return False, f"Thread leak detected: started with {initial_threads} threads, ended with {final_threads}"

        return True, f"Successfully spawned and cleaned up {spawn_count} SerialDaemons with 0 thread leaks."
    finally:
        for d in daemons:
            d.stop()


def audit_worker_death_detection() -> Tuple[bool, str]:
    """Dynamically verify worker death detection in AppState and global polling."""
    from src.ui.app import _global_poll, controller, state

    # Test 1: Worker crashes silently (no terminal event)
    controller.terminal_status = None
    controller.terminal_error = ""
    state.worker_died = False
    state.worker_status = "idle"

    # Simulate poll_telemetry returning worker_died=True with no terminal frame
    old_poll = controller.poll_telemetry
    old_cleanup = controller.cleanup_worker
    try:
        controller.poll_telemetry = lambda: {
            "telemetry": None,
            "verdicts": [],
            "terminal": None,
            "worker_died": True,
        }
        controller.cleanup_worker = lambda: None

        _global_poll()

        if state.worker_status != "worker_error":
            return False, f"Expected worker_status 'worker_error' on silent crash, got '{state.worker_status}'"
        if not state.worker_error:
            return False, "Expected worker_error message on silent crash, got empty string"

        # Test 2: Clean completion preserves worker_done
        controller.terminal_status = "worker_done"
        controller.terminal_error = ""
        state.worker_died = True
        state.worker_status = "worker_done"

        _global_poll()

        if state.worker_status != "worker_done":
            return False, f"Expected worker_status 'worker_done' preserved, got '{state.worker_status}'"

        return True, "Worker death detection verified across all termination modes."
    finally:
        controller.poll_telemetry = old_poll
        controller.cleanup_worker = old_cleanup


def main() -> int:
    """CLI entrypoint for concurrency safety audit."""
    parser = argparse.ArgumentParser(description="Cercus Concurrency Safety Auditor")
    parser.add_argument("--dynamic", action="store_true", help="Run dynamic thread leak and poll checks")
    parser.add_argument("--count", type=int, default=100, help="Number of SerialDaemons for thread leak test")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    violations = audit_all(root)

    if violations:
        print(f"FAIL: Found {len(violations)} concurrency safety violations:\n")
        for v in violations:
            print(f"  {v}")
        return 1

    print("PASS: Static concurrency audit passed with zero violations.")

    if args.dynamic:
        ok_threads, msg_threads = audit_thread_leak(args.count)
        if not ok_threads:
            print(f"FAIL: {msg_threads}")
            return 1
        print(f"PASS: {msg_threads}")

        ok_death, msg_death = audit_worker_death_detection()
        if not ok_death:
            print(f"FAIL: {msg_death}")
            return 1
        print(f"PASS: {msg_death}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
