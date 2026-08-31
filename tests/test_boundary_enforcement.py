"""Tests for Architectural Boundary Enforcement and Process Isolation."""
from pathlib import Path

import pytest

from scripts.audit_boundaries import BoundaryAuditor, audit_all, audit_file


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_entire_repo_passes_boundary_audit() -> None:
    """Verify that every file in the codebase satisfies architectural boundaries."""
    violations = audit_all(ROOT_DIR)
    if violations:
        msg = "\n".join(str(v) for v in violations)
        pytest.fail(f"Architectural boundary violations found:\n{msg}")


def test_forbidden_ipc_primitive_imports() -> None:
    """Verify detection of forbidden multiprocessing shared memory and primitives."""
    src = """
from multiprocessing import shared_memory, Value, Array, Manager, Pipe
import multiprocessing.shared_memory
"""
    auditor = BoundaryAuditor("src/workers/custom_worker.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("forbidden-ipc-primitive") >= 5


def test_forbidden_ipc_attribute_access() -> None:
    """Verify detection of mp.Value, mp.Array, mp.Pipe, mp.shared_memory usage."""
    src = """
import multiprocessing as mp

def setup():
    val = mp.Value('i', 0)
    arr = mp.Array('d', [1.0, 2.0])
    pipe1, pipe2 = mp.Pipe()
    mgr = mp.Manager()
"""
    auditor = BoundaryAuditor("src/workers/custom_worker.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("forbidden-ipc-primitive") >= 4


def test_global_mutable_state_detected() -> None:
    """Verify detection of global and nonlocal statements."""
    src = """
_state = 0

def update():
    global _state
    _state += 1
"""
    auditor = BoundaryAuditor("src/core/custom_logic.py", ROOT_DIR, src)
    violations = auditor.audit()
    assert any(v.category == "forbidden-global-statement" for v in violations)


def test_worker_importing_ui_detected() -> None:
    """Verify workers cannot import UI modules or UI frameworks."""
    src = """
from src.ui.app import AppState
import nicegui
"""
    auditor = BoundaryAuditor("src/workers/stimulus_worker.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("worker-import-ui") == 2


def test_core_import_violations_detected() -> None:
    """Verify core infrastructure cannot import models, workers, or UI."""
    src = """
from src.models.paradigm import BaseParadigm
from src.workers.stimulus_worker import GenericWorker
from src.ui.controller import ExperimentController
"""
    auditor = BoundaryAuditor("src/core/hardware.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("core-import-violation") == 3


def test_model_import_violations_detected() -> None:
    """Verify paradigm models cannot import core, workers, or UI."""
    src = """
from src.core.hardware import SerialDaemon
from src.workers.stimulus_worker import worker_entry
from src.ui.state import AppState
"""
    auditor = BoundaryAuditor("src/models/custom_paradigm.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("model-import-violation") == 3


def test_ui_importing_core_detected() -> None:
    """Verify UI cannot import core hardware, renderers, or loggers."""
    src = """
from src.core.hardware import SerialDaemon
from src.core.render import CoreRenderer
"""
    auditor = BoundaryAuditor("src/ui/pages/dashboard.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("ui-import-violation") == 2


def test_ui_non_controller_importing_workers_detected() -> None:
    """Verify UI pages/components cannot import workers directly."""
    src = """
from src.workers.stimulus_worker import worker_entry
"""
    auditor = BoundaryAuditor("src/ui/pages/dashboard.py", ROOT_DIR, src)
    violations = auditor.audit()
    assert any(v.category == "ui-import-violation" for v in violations)


def test_ui_controller_importing_worker_class_detected() -> None:
    """Verify controller can import worker entry functions but not worker classes."""
    src = """
from src.workers.stimulus_worker import GenericWorker, worker_entry
"""
    auditor = BoundaryAuditor("src/ui/controller.py", ROOT_DIR, src)
    violations = auditor.audit()
    assert len(violations) == 1
    assert violations[0].category == "ui-import-violation"
    assert "GenericWorker" in violations[0].message


def test_ui_direct_hardware_instantiation_detected() -> None:
    """Verify UI cannot directly instantiate hardware or renderer drivers."""
    src = """
def bad_ui_action():
    daemon = SerialDaemon("COM3")
    renderer = CoreRenderer((800, 600), False, 0, False)
"""
    auditor = BoundaryAuditor("src/ui/components/hw_status.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("ui-hardware-instantiation") == 2


def test_zero_allocation_in_kinematics_hot_paths() -> None:
    """Verify that list/dict allocations inside KinematicEngine hot paths are caught."""
    src = """
class KinematicEngine:
    def update(self, t: float, dx: float, dy: float, dz: float):
        allocated_list = [dx, dy, dz]
        allocated_dict = {"dx": dx}
        tmp = list()
"""
    auditor = BoundaryAuditor("src/core/kinematics.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("zero-allocation-violation") == 3


def test_ipc_payload_safety() -> None:
    """Verify detection of non-serializable objects enqueued to IPC queues."""
    src = """
import queue

def push(cmd_queue):
    cmd_queue.put(lambda x: x + 1)
    cmd_queue.put_nowait(Lock())
"""
    auditor = BoundaryAuditor("src/ui/controller.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert cats.count("ipc-payload-violation") == 2


def test_renderer_statelessness_detected() -> None:
    """Verify detection of stateful instance variables or stateful methods in CoreRenderer."""
    src = """
class CoreRenderer:
    def __init__(self):
        self.win = None
        self.trial_counter = 0
        self.current_time = 0.0

    def update_trial(self):
        pass
"""
    auditor = BoundaryAuditor("src/core/render.py", ROOT_DIR, src)
    violations = auditor.audit()
    cats = [v.category for v in violations]
    assert "renderer-stateful-variable" in cats
    assert "renderer-stateful-method" in cats
    assert cats.count("renderer-stateful-variable") == 2
    assert cats.count("renderer-stateful-method") == 1

