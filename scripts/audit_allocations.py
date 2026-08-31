"""AST and Dynamic Zero-Allocation Auditor for Cercus hot paths.

Audits:
1. AST static scan of src/core/kinematics.py (KinematicEngine.update, evaluate_trigger, reset).
2. AST static scan of src/workers/stimulus_worker.py (GenericWorker._drain_hardware inner loop).
3. AST static scan of src/core/hardware.py (KinematicsParser._apply_calibration buffer reuse).
4. Slot completeness verification on KinematicEngine (__slots__ coverage).
5. Dynamic memory profiling via tracemalloc over 10,000 frames on hot methods.
"""

import argparse
import ast
import os
import sys
import tracemalloc
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# Ensure project root is in sys.path for direct CLI execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.hardware import KinematicsParser
from src.core.kinematics import KinematicEngine


FORBIDDEN_CALL_NAMES: Set[str] = {
    "list",
    "dict",
    "set",
}


class AllocationViolation:
    """Represents a zero-allocation rule violation."""

    def __init__(self, file_path: str, line: int, category: str, message: str) -> None:
        """Initialize an allocation violation."""
        self.file_path = file_path
        self.line = line
        self.category = category
        self.message = message

    def __str__(self) -> str:
        """Format violation as human-readable string."""
        return f"{self.file_path}:{self.line} [{self.category}] {self.message}"


class AllocationAuditor(ast.NodeVisitor):
    """AST visitor enforcing zero-allocation constraints in critical telemetry and kinematic hot paths."""

    def __init__(self, file_path: str, root_dir: Path, source_code: str) -> None:
        """Initialize the allocation auditor."""
        self.file_path = str(file_path)
        self.source_code = source_code
        self.violations: List[AllocationViolation] = []

        try:
            rel = Path(file_path).resolve().relative_to(root_dir.resolve())
            self.rel_path = rel.as_posix()
        except ValueError:
            self.rel_path = Path(file_path).as_posix()

        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None
        self.class_slots: Dict[str, Set[str]] = {}
        self.class_init_attrs: Dict[str, Set[str]] = {}

    def audit(self) -> List[AllocationViolation]:
        """Run AST audit on the python source."""
        try:
            tree = ast.parse(self.source_code, filename=self.file_path)
        except SyntaxError as e:
            self.violations.append(
                AllocationViolation(self.file_path, e.lineno or 1, "syntax-error", str(e))
            )
            return self.violations

        self.visit(tree)
        self._check_slots_coverage()
        return self.violations

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definition and extract __slots__ if present."""
        prev_class = self.current_class
        self.current_class = node.name

        # Extract __slots__ declarations
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "__slots__":
                        slots = self._extract_slots(stmt.value)
                        self.class_slots[node.name] = slots

        self.generic_visit(node)
        self.current_class = prev_class

    @staticmethod
    def _extract_slots(val_node: ast.AST) -> Set[str]:
        """Extract slot names from tuple or list literal."""
        slots: Set[str] = set()
        if isinstance(val_node, (ast.Tuple, ast.List)):
            for elt in val_node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    slots.add(elt.value)
        return slots

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition and check hot path constraints."""
        prev_func = self.current_function
        self.current_function = node.name

        # Track attribute assignments in __init__
        if node.name == "__init__" and self.current_class:
            attrs = self._extract_self_attrs(node)
            self.class_init_attrs[self.current_class] = attrs

        # Check KinematicEngine hot paths
        if self.rel_path == "src/core/kinematics.py" or (self.current_class == "KinematicEngine"):
            if self.current_class == "KinematicEngine" and node.name in ("update", "evaluate_trigger", "reset"):
                self._check_kinematics_hot_function(node)

        # Check stimulus_worker.py GenericWorker._drain_hardware
        if self.rel_path == "src/workers/stimulus_worker.py" or (self.current_class == "GenericWorker"):
            if self.current_class == "GenericWorker" and node.name == "_drain_hardware":
                self._check_drain_hardware(node)

        # Check hardware.py KinematicsParser._apply_calibration
        if self.rel_path == "src/core/hardware.py" or (self.current_class == "KinematicsParser"):
            if self.current_class == "KinematicsParser" and node.name == "_apply_calibration":
                self._check_apply_calibration(node)

        self.generic_visit(node)
        self.current_function = prev_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition."""
        prev_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev_func

    @staticmethod
    def _extract_self_attrs(func_node: ast.FunctionDef) -> Set[str]:
        """Extract self.<attr> target names assigned in __init__."""
        attrs: Set[str] = set()
        for child in ast.walk(func_node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                        attrs.add(target.attr)
        return attrs

    def _check_slots_coverage(self) -> None:
        """Verify that KinematicEngine declares __slots__ and covers all initialized attributes."""
        if self.rel_path == "src/core/kinematics.py" or "KinematicEngine" in self.class_slots:
            if "KinematicEngine" not in self.class_slots:
                self.violations.append(
                    AllocationViolation(
                        self.file_path,
                        1,
                        "missing-slots",
                        "KinematicEngine must define __slots__ to prevent dynamic instance dictionary allocation.",
                    )
                )
            else:
                slots = self.class_slots["KinematicEngine"]
                init_attrs = self.class_init_attrs.get("KinematicEngine", set())
                unslotted = init_attrs - slots
                if unslotted:
                    self.violations.append(
                        AllocationViolation(
                            self.file_path,
                            1,
                            "incomplete-slots",
                            f"KinematicEngine instance attributes not in __slots__: {', '.join(sorted(unslotted))}.",
                        )
                    )

    def _check_kinematics_hot_function(self, func_node: ast.FunctionDef) -> None:
        """Enforce zero heap allocation in KinematicEngine hot methods."""
        for child in ast.walk(func_node):
            # Check forbidden literals and comprehensions
            if isinstance(child, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
                self.violations.append(
                    AllocationViolation(
                        self.file_path,
                        child.lineno,
                        "forbidden-allocation",
                        f"Allocation of '{type(child).__name__}' inside hot path '{self.current_function}' is forbidden.",
                    )
                )
            elif isinstance(child, ast.Call):
                func_id = None
                if isinstance(child.func, ast.Name):
                    func_id = child.func.id
                if func_id in FORBIDDEN_CALL_NAMES:
                    self.violations.append(
                        AllocationViolation(
                            self.file_path,
                            child.lineno,
                            "forbidden-allocation",
                            f"Call to '{func_id}()' inside hot path '{self.current_function}' is forbidden.",
                        )
                    )

    def _check_drain_hardware(self, func_node: ast.FunctionDef) -> None:
        """Enforce zero allocation in hardware draining loop."""
        for child in ast.walk(func_node):
            # Inside the for loop over items, check for dict(zip(...)) or dynamic list/dict literals
            if isinstance(child, ast.For):
                for loop_child in ast.walk(child):
                    if isinstance(loop_child, ast.Call):
                        if isinstance(loop_child.func, ast.Name) and loop_child.func.id == "dict":
                            # Check if dict(zip(...)) is inside per-sample loop
                            self.violations.append(
                                AllocationViolation(
                                    self.file_path,
                                    loop_child.lineno,
                                    "forbidden-loop-allocation",
                                    "Per-sample 'dict()' instantiation in hardware drain loop is forbidden.",
                                )
                            )
                        elif isinstance(loop_child.func, ast.Name) and loop_child.func.id == "zip":
                            self.violations.append(
                                AllocationViolation(
                                    self.file_path,
                                    loop_child.lineno,
                                    "forbidden-loop-allocation",
                                    "Per-sample 'zip()' instantiation in hardware drain loop is forbidden.",
                                )
                            )

    def _check_apply_calibration(self, func_node: ast.FunctionDef) -> None:
        """Enforce that KinematicsParser._apply_calibration uses pre-allocated output buffer."""
        for child in ast.walk(func_node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name) and child.func.id == "list":
                    self.violations.append(
                        AllocationViolation(
                            self.file_path,
                            child.lineno,
                            "forbidden-allocation",
                            "Call to 'list()' inside '_apply_calibration' is forbidden. Must reuse pre-allocated _out_buf.",
                        )
                    )
            elif isinstance(child, (ast.ListComp, ast.DictComp, ast.SetComp)):
                self.violations.append(
                    AllocationViolation(
                        self.file_path,
                        child.lineno,
                        "forbidden-allocation",
                        f"Comprehension '{type(child).__name__}' inside '_apply_calibration' is forbidden.",
                    )
                )


def audit_source_code(source_code: str, file_path: str = "src/core/kinematics.py", root_dir: Optional[Path] = None) -> List[AllocationViolation]:
    """Audit source code string directly."""
    if root_dir is None:
        root_dir = Path.cwd()
    auditor = AllocationAuditor(file_path, root_dir, source_code)
    return auditor.audit()


def audit_file(file_path: Path, root_dir: Path) -> List[AllocationViolation]:
    """Audit a single python file."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [AllocationViolation(str(file_path), 1, "read-error", str(e))]

    auditor = AllocationAuditor(str(file_path), root_dir, source_code=source)
    return auditor.audit()


def audit_ast_all(root_dir: Path) -> List[AllocationViolation]:
    """Audit all relevant source files for zero-allocation constraints."""
    target_files = [
        root_dir / "src" / "core" / "kinematics.py",
        root_dir / "src" / "core" / "hardware.py",
        root_dir / "src" / "workers" / "stimulus_worker.py",
    ]
    violations: List[AllocationViolation] = []
    for f in target_files:
        if f.exists():
            violations.extend(audit_file(f, root_dir))
    return violations


def run_dynamic_allocation_profiling(iterations: int = 10000) -> List[AllocationViolation]:
    """Profile hot paths with tracemalloc to ensure zero heap allocations during steady-state loops."""
    violations: List[AllocationViolation] = []

    # 1. Profile KinematicEngine.update
    eng = KinematicEngine()
    for i in range(100):
        eng.update(0.005 * i, 1.0, 1.0, 0.5)

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()
    for i in range(100, 100 + iterations):
        eng.update(0.005 * i, 1.0, 1.0, 0.5)
    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    kin_diffs = [
        s for s in diff
        if "kinematics.py" in s.traceback.format()[0] and s.size_diff > 0
    ]
    if kin_diffs:
        for s in kin_diffs:
            violations.append(
                AllocationViolation(
                    "src/core/kinematics.py",
                    s.traceback[0].lineno,
                    "dynamic-allocation-leak",
                    f"KinematicEngine.update allocated {s.size_diff} B over {iterations} iterations: {s}",
                )
            )

    # 2. Profile KinematicEngine.evaluate_trigger
    eng.reset()
    eng.update(0.01, 5.0, 5.0, 2.0)
    eng.update(0.02, 5.0, 5.0, 2.0)
    for _ in range(100):
        eng.evaluate_trigger(10.0, 5.0, 20.0, 50.0)

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()
    for _ in range(iterations):
        eng.evaluate_trigger(10.0, 5.0, 20.0, 50.0)
    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    trig_diffs = [
        s for s in diff
        if "kinematics.py" in s.traceback.format()[0] and s.size_diff > 0
    ]
    if trig_diffs:
        for s in trig_diffs:
            violations.append(
                AllocationViolation(
                    "src/core/kinematics.py",
                    s.traceback[0].lineno,
                    "dynamic-allocation-leak",
                    f"KinematicEngine.evaluate_trigger allocated {s.size_diff} B: {s}",
                )
            )

    # 3. Profile KinematicsParser._apply_calibration
    parser = KinematicsParser()
    fields = [0, 10, 20, 30, 0]
    for _ in range(100):
        parser._apply_calibration(fields)

    tracemalloc.start()
    snap1 = tracemalloc.take_snapshot()
    for _ in range(iterations):
        parser._apply_calibration(fields)
    snap2 = tracemalloc.take_snapshot()
    tracemalloc.stop()

    diff = snap2.compare_to(snap1, "lineno")
    hw_diffs = [
        s for s in diff
        if "hardware.py" in s.traceback.format()[0] and s.size_diff > 0
    ]
    if hw_diffs:
        for s in hw_diffs:
            violations.append(
                AllocationViolation(
                    "src/core/hardware.py",
                    s.traceback[0].lineno,
                    "dynamic-allocation-leak",
                    f"KinematicsParser._apply_calibration allocated {s.size_diff} B: {s}",
                )
            )

    return violations


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Audit zero-allocation compliance across Cercus hot paths.")
    parser.add_argument(
        "--check",
        choices=["all", "ast", "dynamic"],
        default="all",
        help="Check mode: 'ast' (static AST scan), 'dynamic' (tracemalloc profiling), or 'all' (default: all)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10000,
        help="Number of iterations for dynamic profiling (default: 10000)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    violations: List[AllocationViolation] = []

    if args.check in ("all", "ast"):
        violations.extend(audit_ast_all(root))

    if args.check in ("all", "dynamic"):
        violations.extend(run_dynamic_allocation_profiling(iterations=args.iterations))

    if not violations:
        print(f"PASS: Zero-allocation audit passed ({args.check}) with zero violations.")
        return 0

    print(f"FAIL: Found {len(violations)} zero-allocation violations ({args.check}):\n")
    for v in violations:
        print(f"  {v}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
