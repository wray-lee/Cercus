"""Zero-allocation static AST and dynamic tracemalloc profiling tests."""

import tracemalloc
from pathlib import Path

import pytest

from scripts.audit_allocations import (
    AllocationAuditor,
    audit_ast_all,
    audit_file,
    audit_source_code,
    run_dynamic_allocation_profiling,
)
from src.core.hardware import KinematicsParser
from src.core.kinematics import KinematicEngine


ROOT_DIR = Path(__file__).resolve().parent.parent


# ===========================================================================
# 1. Static AST Scan Tests
# ===========================================================================


def test_entire_repo_ast_zero_allocation() -> None:
    """Verify that all target hot path files have zero forbidden allocations."""
    violations = audit_ast_all(ROOT_DIR)
    if violations:
        msg = "\n".join(str(v) for v in violations)
        pytest.fail(f"Zero-allocation violations found:\n{msg}")


def test_kinematics_ast_zero_allocation() -> None:
    """Verify KinematicEngine hot paths (update, evaluate_trigger, reset) have no allocations."""
    kin_file = ROOT_DIR / "src" / "core" / "kinematics.py"
    violations = audit_file(kin_file, ROOT_DIR)
    assert not violations, f"Violations in kinematics.py: {[str(v) for v in violations]}"


def test_stimulus_worker_ast_zero_allocation() -> None:
    """Verify GenericWorker._drain_hardware per-sample loop has no forbidden allocations."""
    worker_file = ROOT_DIR / "src" / "workers" / "stimulus_worker.py"
    violations = audit_file(worker_file, ROOT_DIR)
    assert not violations, f"Violations in stimulus_worker.py: {[str(v) for v in violations]}"


def test_hardware_parser_ast_zero_allocation() -> None:
    """Verify KinematicsParser._apply_calibration reuses pre-allocated buffer without list()."""
    hw_file = ROOT_DIR / "src" / "core" / "hardware.py"
    violations = audit_file(hw_file, ROOT_DIR)
    assert not violations, f"Violations in hardware.py: {[str(v) for v in violations]}"


def test_ast_auditor_detects_forbidden_allocation_in_kinematics() -> None:
    """Verify that AST auditor flags forbidden list/dict/set/comprehension allocations."""
    bad_code = """
class KinematicEngine:
    __slots__ = ("_last_t",)

    def __init__(self):
        self._last_t = 0.0

    def update(self, t: float, dx: float, dy: float, dz: float):
        allocated_list = [dx, dy, dz]
        allocated_dict = {"t": t}
        allocated_set = {dx, dy}
        comp = [x * 2 for x in (dx, dy)]
        called_list = list()
        called_dict = dict()
"""
    violations = audit_source_code(bad_code, "src/core/kinematics.py", ROOT_DIR)
    cats = [v.category for v in violations]
    assert cats.count("forbidden-allocation") >= 6


def test_ast_auditor_detects_forbidden_loop_allocation_in_worker() -> None:
    """Verify that AST auditor flags per-sample dict() or zip() in hardware drain loop."""
    bad_code = """
class GenericWorker:
    def _drain_hardware(self, logger, hw_daemon):
        items = hw_daemon.drain_queue()
        for sys_t, raw in items:
            tel = dict(zip(field_keys, cal_fields))
"""
    violations = audit_source_code(bad_code, "src/workers/stimulus_worker.py", ROOT_DIR)
    cats = [v.category for v in violations]
    assert "forbidden-loop-allocation" in cats


def test_ast_auditor_detects_missing_slots() -> None:
    """Verify that AST auditor flags classes missing __slots__ declaration."""
    bad_code = """
class KinematicEngine:
    def __init__(self):
        self.dx = 0.0
"""
    violations = audit_source_code(bad_code, "src/core/kinematics.py", ROOT_DIR)
    assert any(v.category == "missing-slots" for v in violations)


def test_ast_auditor_detects_incomplete_slots() -> None:
    """Verify that AST auditor flags unslotted instance attributes assigned in __init__."""
    bad_code = """
class KinematicEngine:
    __slots__ = ("_last_t",)

    def __init__(self):
        self._last_t = 0.0
        self._unslotted_attr = 123.0
"""
    violations = audit_source_code(bad_code, "src/core/kinematics.py", ROOT_DIR)
    assert any(v.category == "incomplete-slots" for v in violations)


# ===========================================================================
# 2. Runtime and Tracemalloc Profiling Tests
# ===========================================================================


def test_kinematic_engine_slots_runtime_enforcement() -> None:
    """Verify KinematicEngine does not allocate an instance __dict__."""
    eng = KinematicEngine()
    assert not hasattr(eng, "__dict__"), "KinematicEngine should not have __dict__"
    with pytest.raises(AttributeError):
        eng._unslotted_dynamic_field = 999.0  # type: ignore[attr-defined]


def test_tracemalloc_kinematic_engine_update_zero_allocation() -> None:
    """Profile KinematicEngine.update across 10,000 iterations for zero net heap allocations."""
    eng = KinematicEngine()
    # Warm up to populate any runtime caches
    for i in range(100):
        eng.update(0.005 * i, 1.0, 1.0, 0.5)

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()

    for i in range(100, 10100):
        eng.update(0.005 * i, 1.0, 1.0, 0.5)

    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    kin_diffs = [
        s for s in diff
        if "kinematics.py" in s.traceback.format()[0] and s.size_diff > 0
    ]
    assert not kin_diffs, f"Unexpected heap allocations in update(): {kin_diffs}"


def test_tracemalloc_kinematic_engine_evaluate_trigger_zero_allocation() -> None:
    """Profile KinematicEngine.evaluate_trigger across 10,000 iterations for zero heap allocations."""
    eng = KinematicEngine()
    eng.update(0.01, 5.0, 5.0, 2.0)
    eng.update(0.02, 5.0, 5.0, 2.0)

    # Warm up
    for _ in range(100):
        eng.evaluate_trigger(10.0, 5.0, 20.0, 50.0)

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()

    for _ in range(10000):
        eng.evaluate_trigger(10.0, 5.0, 20.0, 50.0)

    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    kin_diffs = [
        s for s in diff
        if "kinematics.py" in s.traceback.format()[0] and s.size_diff > 0
    ]
    assert not kin_diffs, f"Unexpected heap allocations in evaluate_trigger(): {kin_diffs}"


def test_tracemalloc_kinematic_engine_reset_and_properties_zero_allocation() -> None:
    """Profile reset() and public property accessors for zero heap allocations."""
    eng = KinematicEngine()
    eng.update(0.01, 2.0, 3.0, 1.0)
    eng.update(0.02, 2.0, 3.0, 1.0)

    for _ in range(50):
        _ = eng.cum_dz
        _ = eng.turn_speed
        _ = eng.move_speed
        _ = eng.peak_move_speed
        _ = eng.effective_speed
        _ = eng.cum_disp
        _ = eng.pos_x
        _ = eng.pos_y

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()

    for _ in range(5000):
        _ = eng.cum_dz
        _ = eng.turn_speed
        _ = eng.move_speed
        _ = eng.peak_move_speed
        _ = eng.effective_speed
        _ = eng.cum_disp
        _ = eng.pos_x
        _ = eng.pos_y

    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    kin_diffs = [
        s for s in diff
        if "kinematics.py" in s.traceback.format()[0] and s.size_diff > 0
    ]
    assert not kin_diffs, f"Unexpected heap allocations in property getters: {kin_diffs}"


def test_tracemalloc_hardware_parser_calibration_zero_allocation() -> None:
    """Profile KinematicsParser._apply_calibration for zero heap allocations."""
    parser = KinematicsParser()
    fields = [0, 10, 20, 30, 0]

    for _ in range(100):
        parser._apply_calibration(fields)

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()

    for _ in range(10000):
        parser._apply_calibration(fields)

    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    hw_diffs = [
        s for s in diff
        if "hardware.py" in s.traceback.format()[0] and s.size_diff > 0
    ]
    assert not hw_diffs, f"Unexpected heap allocations in _apply_calibration: {hw_diffs}"


def test_tracemalloc_simulated_drain_hardware_zero_allocation() -> None:
    """Simulate hardware draining hot loop and verify zero net heap allocations."""
    parser = KinematicsParser()
    engine = KinematicEngine()
    field_keys = parser.field_keys
    dx_idx = field_keys.index("dx")
    dy_idx = field_keys.index("dy")
    dz_idx = field_keys.index("dz")
    ard_idx = field_keys.index("ard_time")
    last_tel_data = {k: 0.0 for k in field_keys}
    raw = "100,10,20,30,0"

    # Warmup
    for i in range(100):
        sys_t = 0.005 * i
        row = parser.parse(sys_t, raw, 0)
        if row is not None:
            cal_fields = row[1:-1]
            engine.update(
                sys_t,
                float(cal_fields[dx_idx]),
                float(cal_fields[dy_idx]),
                float(cal_fields[dz_idx]),
            )
            for idx, k in enumerate(field_keys):
                last_tel_data[k] = cal_fields[idx]

    row = None
    cal_fields = None

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()

    for i in range(100, 10100):
        sys_t = 0.005 * i
        row = parser.parse(sys_t, raw, 0)
        if row is not None:
            cal_fields = row[1:-1]
            engine.update(
                sys_t,
                float(cal_fields[dx_idx]),
                float(cal_fields[dy_idx]),
                float(cal_fields[dz_idx]),
            )
            for idx, k in enumerate(field_keys):
                last_tel_data[k] = cal_fields[idx]

    row = None
    cal_fields = None

    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    loop_diffs = [
        s for s in diff
        if any(f in s.traceback.format()[0] for f in ("kinematics.py", "hardware.py")) and s.size_diff > 0
    ]
    assert not loop_diffs, f"Unexpected heap allocations in simulated drain loop: {loop_diffs}"


def test_dynamic_profiling_runner() -> None:
    """Verify run_dynamic_allocation_profiling runs and returns no violations."""
    violations = run_dynamic_allocation_profiling(iterations=5000)
    assert not violations, f"Dynamic profiling violations: {[str(v) for v in violations]}"
