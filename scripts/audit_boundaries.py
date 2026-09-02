"""AST-based Architectural Boundary and Process Isolation Auditor for Cercus.

Audits:
1. Forbidden IPC and shared memory primitives (multiprocessing.shared_memory, Value, Array, Manager, Pipe).
2. Global mutable state statements (ast.Global, ast.Nonlocal) across all subsystem layers.
3. Subsystem import boundaries & layer isolation:
   - src/workers/ must NOT import src.ui.* or UI frameworks (nicegui, pywebview, etc.).
   - src/core/ must NOT import src.ui.*, src.workers.*, src.models.*, or UI frameworks.
   - src/models/ must NOT import src.ui.*, src.workers.*, src.core.*, or UI frameworks.
   - src/ui/ must NOT import src.core.* or worker internal classes (GenericWorker, CalibrationWorker).
     Only src/ui/controller.py may import worker entry points (worker_entry, create_ipc_queues)
     for mp.Process target binding.
4. UI direct hardware / renderer instantiation prevention.
5. Zero-allocation constraints on KinematicEngine hot paths (update, evaluate_trigger).
6. IPC queue payload constraints (no passing non-serializable objects like Locks, Threads, Lambdas).
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


FORBIDDEN_IPC_NAMES: Set[str] = {
    "shared_memory",
    "Value",
    "Array",
    "Manager",
    "Pipe",
    "RawValue",
    "RawArray",
    "sharedctypes",
}

UI_MODULE_PREFIXES: Set[str] = {
    "nicegui",
    "pywebview",
    "webview",
    "starlette",
    "fastapi",
    "uvicorn",
}

FORBIDDEN_UI_INSTANTIATIONS: Set[str] = {
    "SerialDaemon",
    "MockSerialDaemon",
    "KinematicsParser",
    "CoreRenderer",
    "GenericWorker",
    "CalibrationWorker",
    "KinematicEngine",
    "GroundTruthLogger",
}

NON_SERIALIZABLE_PAYLOAD_TYPES: Set[str] = {
    "Lock",
    "RLock",
    "Event",
    "Condition",
    "Semaphore",
    "Thread",
    "Process",
    "Serial",
    "Socket",
    "Window",
}

ALLOWED_RENDERER_ATTRS: Set[str] = {
    "win",
    "_win",
    "window",
    "_window",
    "surface",
    "_surface",
    "clock",
    "_clock",
    "objects",
    "_objects",
    "visual",
    "_visual",
}

FORBIDDEN_RENDERER_IMPORTS: Set[str] = {
    "src.core.hardware",
    "src.core.kinematics",
    "src.core.logger",
    "src.models",
    "src.workers",
    "src.ui",
    "threading",
    "multiprocessing",
    "serial",
    "socket",
}

FORBIDDEN_RENDERER_METHODS: Set[str] = {
    "update_trial",
    "step",
    "on_tick",
    "classify_response",
    "evaluate_trigger",
    "calculate_metrics",
    "log_event",
    "process_telemetry",
    "handle_trial",
    "start_session",
    "stop_session",
}


class Violation:
    """Represents an architectural boundary violation."""

    def __init__(self, file_path: str, line: int, category: str, message: str) -> None:
        self.file_path = file_path
        self.line = line
        self.category = category
        self.message = message

    def __str__(self) -> str:
        return f"{self.file_path}:{self.line} [{self.category}] {self.message}"


class BoundaryAuditor(ast.NodeVisitor):
    """AST visitor enforcing Cercus process isolation and boundary rules."""

    def __init__(self, file_path: str, root_dir: Path, source_code: str) -> None:
        self.file_path = str(file_path)
        self.source_code = source_code
        self.violations: List[Violation] = []

        try:
            rel = Path(file_path).resolve().relative_to(root_dir.resolve())
            self.rel_path = rel.as_posix()
        except ValueError:
            self.rel_path = Path(file_path).as_posix()

        self.layer = self._determine_layer(self.rel_path)
        self.mp_aliases: Set[str] = set()
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None

    @staticmethod
    def _determine_layer(rel_path: str) -> str:
        if rel_path.startswith("src/workers/"):
            return "worker"
        if rel_path.startswith("src/core/"):
            return "core"
        if rel_path.startswith("src/models/"):
            return "model"
        if rel_path.startswith("src/ui/"):
            return "ui"
        if rel_path.startswith("tests/"):
            return "tests"
        if rel_path.startswith("scripts/"):
            return "scripts"
        return "root"

    def audit(self) -> List[Violation]:
        """Run AST audit on the source tree."""
        try:
            tree = ast.parse(self.source_code, filename=self.file_path)
        except SyntaxError as e:
            self.violations.append(
                Violation(self.file_path, e.lineno or 1, "syntax-error", str(e))
            )
            return self.violations

        self.visit(tree)
        return self.violations

    # ------------------------------------------------------------------
    # Import boundary and forbidden IPC checking
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod_name = alias.name
            as_name = alias.asname or alias.name

            # Track multiprocessing aliases
            if mod_name == "multiprocessing":
                self.mp_aliases.add(as_name)

            # 1. Global: Forbidden IPC shared memory primitives
            if mod_name.startswith("multiprocessing.shared_memory"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        node.lineno,
                        "forbidden-ipc-primitive",
                        f"Import '{mod_name}' is forbidden. Process isolation requires pure mp.Queue only.",
                    )
                )

            # Renderer specific import check
            if self.rel_path == "src/core/render.py":
                for forbidden in FORBIDDEN_RENDERER_IMPORTS:
                    if mod_name == forbidden or mod_name.startswith(forbidden + "."):
                        self.violations.append(
                            Violation(
                                self.file_path,
                                node.lineno,
                                "renderer-forbidden-import",
                                f"CoreRenderer must not import '{mod_name}'. Violates renderer statelessness boundary.",
                            )
                        )

            # 2. Layer boundary checks
            self._check_module_import_boundary(mod_name, node.lineno)

        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        level = node.level

        # Track multiprocessing imports
        if mod == "multiprocessing" or mod.startswith("multiprocessing."):
            for alias in node.names:
                if alias.name in FORBIDDEN_IPC_NAMES:
                    self.violations.append(
                        Violation(
                            self.file_path,
                            node.lineno,
                            "forbidden-ipc-primitive",
                            f"Import '{alias.name}' from '{mod}' is forbidden. Process isolation requires pure mp.Queue only.",
                        )
                    )

        # Layer boundary checks
        if level == 0 and mod:
            for alias in node.names:
                full_name = f"{mod}.{alias.name}" if alias.name != "*" else mod
                self._check_module_import_boundary(full_name, node.lineno, imported_item=alias.name, module_base=mod)

        self.generic_visit(node)

    def _check_module_import_boundary(
        self,
        full_name: str,
        lineno: int,
        imported_item: Optional[str] = None,
        module_base: Optional[str] = None,
    ) -> None:
        top_pkg = full_name.split(".")[0]
        base = module_base or full_name

        # --- Specific Core Renderer Immutability & Stateless Checks ---
        if self.rel_path == "src/core/render.py":
            for forbidden in FORBIDDEN_RENDERER_IMPORTS:
                if full_name == forbidden or full_name.startswith(forbidden + ".") or base == forbidden:
                    self.violations.append(
                        Violation(
                            self.file_path,
                            lineno,
                            "renderer-forbidden-import",
                            f"CoreRenderer must not import '{full_name}'. Violates renderer statelessness boundary.",
                        )
                    )

        # --- Worker Layer Checks ---
        if self.layer == "worker":
            if full_name.startswith("src.ui") or base.startswith("src.ui"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "worker-import-ui",
                        f"Worker process must not import UI module '{full_name}'. Violates physical process isolation.",
                    )
                )
            if top_pkg in UI_MODULE_PREFIXES:
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "worker-import-ui",
                        f"Worker process must not import UI framework '{full_name}'.",
                    )
                )

        # --- Core Layer Checks ---
        elif self.layer == "core":
            if full_name.startswith("src.ui") or base.startswith("src.ui"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "core-import-violation",
                        f"Core infrastructure must not import UI module '{full_name}'.",
                    )
                )
            if full_name.startswith("src.workers") or base.startswith("src.workers"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "core-import-violation",
                        f"Core infrastructure must not import worker module '{full_name}'.",
                    )
                )
            if full_name.startswith("src.models") or base.startswith("src.models"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "core-import-violation",
                        f"Core infrastructure must remain paradigm-agnostic; cannot import '{full_name}'.",
                    )
                )
            if top_pkg in UI_MODULE_PREFIXES:
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "core-import-violation",
                        f"Core infrastructure must not import UI framework '{full_name}'.",
                    )
                )

        # --- Model / Paradigm Layer Checks ---
        elif self.layer == "model":
            if full_name.startswith("src.ui") or base.startswith("src.ui"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "model-import-violation",
                        f"Paradigm models must not import UI module '{full_name}'.",
                    )
                )
            if full_name.startswith("src.workers") or base.startswith("src.workers"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "model-import-violation",
                        f"Paradigm models must not import worker module '{full_name}'.",
                    )
                )
            if full_name.startswith("src.core") or base.startswith("src.core"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "model-import-violation",
                        f"Paradigm models must not import core infrastructure '{full_name}'. Must remain decoupled.",
                    )
                )
            if top_pkg in UI_MODULE_PREFIXES:
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "model-import-violation",
                        f"Paradigm models must not import UI framework '{full_name}'.",
                    )
                )

        # --- UI Layer Checks ---
        elif self.layer == "ui":
            # UI must never import src.core directly
            if full_name.startswith("src.core") or base.startswith("src.core"):
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "ui-import-violation",
                        f"UI thread must not import core infrastructure '{full_name}'. Hardware and rendering belong in workers.",
                    )
                )

            # Only controller.py can import entrypoints from src.workers
            if full_name.startswith("src.workers") or base.startswith("src.workers"):
                if self.rel_path != "src/ui/controller.py":
                    self.violations.append(
                        Violation(
                            self.file_path,
                            lineno,
                            "ui-import-violation",
                            f"UI component '{self.rel_path}' must not import '{full_name}'. Only controller.py manages workers.",
                        )
                    )
                else:
                    # In controller.py, ensure only entry functions are imported, not worker classes
                    if imported_item in ("GenericWorker", "CalibrationWorker"):
                        self.violations.append(
                            Violation(
                                self.file_path,
                                lineno,
                                "ui-import-violation",
                                f"Controller must not import worker implementation class '{imported_item}'. Use worker_entry function.",
                            )
                        )

    # ------------------------------------------------------------------
    # Global mutable state statement prohibition
    # ------------------------------------------------------------------

    def visit_Global(self, node: ast.Global) -> None:
        if self.layer in ("worker", "core", "model", "ui"):
            names = ", ".join(node.names)
            self.violations.append(
                Violation(
                    self.file_path,
                    node.lineno,
                    "forbidden-global-statement",
                    f"Global statement '{names}' is forbidden. Process isolation requires explicit encapsulation.",
                )
            )
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        if self.layer in ("worker", "core", "model"):
            names = ", ".join(node.names)
            self.violations.append(
                Violation(
                    self.file_path,
                    node.lineno,
                    "forbidden-global-statement",
                    f"Nonlocal statement '{names}' is forbidden in {self.layer} layer.",
                )
            )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Attribute access and Call checks (forbidden primitives & UI hardware instantiation)
    # ------------------------------------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Check mp.Value, mp.shared_memory, mp.Pipe, mp.Array, mp.Manager
        if isinstance(node.value, ast.Name):
            if node.value.id in self.mp_aliases or node.value.id in ("mp", "multiprocessing"):
                if node.attr in FORBIDDEN_IPC_NAMES:
                    self.violations.append(
                        Violation(
                            self.file_path,
                            node.lineno,
                            "forbidden-ipc-primitive",
                            f"Use of 'multiprocessing.{node.attr}' is forbidden. Only mp.Queue and mp.Process are permitted.",
                        )
                    )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev_func = self.current_function
        self.current_function = node.name
        self._check_function_body(node)
        self.generic_visit(node)
        self.current_function = prev_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        prev_func = self.current_function
        self.current_function = node.name
        self._check_function_body(node)
        self.generic_visit(node)
        self.current_function = prev_func

    def _check_function_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # 1. Check KinematicEngine zero-allocation hot paths in src/core/kinematics.py
        if self.rel_path == "src/core/kinematics.py" and self.current_class == "KinematicEngine":
            if node.name in ("update", "evaluate_trigger"):
                self._check_zero_allocation(node)

        # 2. Check CoreRenderer statelessness rules in src/core/render.py
        if self.rel_path == "src/core/render.py" and self.current_class == "CoreRenderer":
            self._check_renderer_stateless_method(node)

    def _check_renderer_stateless_method(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Enforce that CoreRenderer methods do not store trial/timing state or execute logic."""
        if node.name in FORBIDDEN_RENDERER_METHODS:
            self.violations.append(
                Violation(
                    self.file_path,
                    node.lineno,
                    "renderer-stateful-method",
                    f"CoreRenderer method '{node.name}' violates statelessness boundary. "
                    f"Renderer must only perform geometry drawing and window flips.",
                )
            )

        for child in ast.walk(node):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                        attr = target.attr
                        if attr not in ALLOWED_RENDERER_ATTRS and not attr.startswith("_state_cache"):
                            self.violations.append(
                                Violation(
                                    self.file_path,
                                    target.lineno,
                                    "renderer-stateful-variable",
                                    f"CoreRenderer instance variable 'self.{attr}' violates statelessness boundary. "
                                    f"Allowed handles: {', '.join(sorted(ALLOWED_RENDERER_ATTRS))}.",
                                )
                            )

    def _check_zero_allocation(self, func_node: ast.AST) -> None:
        """Ensure no dynamic memory allocation (lists/dicts/sets) occurs in hot loops."""
        for child in ast.walk(func_node):
            # Check for list/dict/set literals or comprehensions
            if isinstance(child, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
                self.violations.append(
                    Violation(
                        self.file_path,
                        child.lineno,
                        "zero-allocation-violation",
                        f"Allocation of '{type(child).__name__}' inside hot path '{self.current_function}' is forbidden.",
                    )
                )
            elif isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name) and child.func.id in ("list", "dict", "set"):
                    self.violations.append(
                        Violation(
                            self.file_path,
                            child.lineno,
                            "zero-allocation-violation",
                            f"Call to '{child.func.id}()' inside hot path '{self.current_function}' is forbidden.",
                        )
                    )

    def visit_Call(self, node: ast.Call) -> None:
        # 1. UI Direct Hardware / Renderer Instantiation Check
        if self.layer == "ui":
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name in FORBIDDEN_UI_INSTANTIATIONS:
                self.violations.append(
                    Violation(
                        self.file_path,
                        node.lineno,
                        "ui-hardware-instantiation",
                        f"UI layer directly references/instantiates '{func_name}'. "
                        f"UI must only communicate with hardware/workers via ExperimentController and Queues.",
                    )
                )

        # 2. IPC Queue Payload Safety Check
        # Check queue.put(...) and queue.put_nowait(...)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("put", "put_nowait"):
            if node.args:
                arg0 = node.args[0]
                self._check_queue_payload(arg0, node.lineno)

        self.generic_visit(node)

    def _check_queue_payload(self, payload_node: ast.AST, lineno: int) -> None:
        """Check that objects put into queues are not non-serializable objects (Locks, Threads, Lambdas)."""
        if isinstance(payload_node, ast.Lambda):
            self.violations.append(
                Violation(
                    self.file_path,
                    lineno,
                    "ipc-payload-violation",
                    "Cannot put lambda function into multiprocessing queue.",
                )
            )
        elif isinstance(payload_node, ast.Call):
            func_name = None
            if isinstance(payload_node.func, ast.Name):
                func_name = payload_node.func.id
            elif isinstance(payload_node.func, ast.Attribute):
                func_name = payload_node.func.attr

            if func_name in NON_SERIALIZABLE_PAYLOAD_TYPES:
                self.violations.append(
                    Violation(
                        self.file_path,
                        lineno,
                        "ipc-payload-violation",
                        f"Cannot put non-serializable object '{func_name}' into multiprocessing queue.",
                    )
                )


def audit_file(file_path: Path, root_dir: Path) -> List[Violation]:
    """Audit a single python file for boundary enforcement."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [Violation(str(file_path), 1, "read-error", str(e))]

    auditor = BoundaryAuditor(str(file_path), root_dir, source)
    return auditor.audit()


def audit_all(root_dir: Path, target_dirs: Optional[List[str]] = None) -> List[Violation]:
    """Audit all python files in target directories."""
    violations: List[Violation] = []
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


def main() -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Audit architectural boundaries in Cercus.")
    parser.add_argument(
        "--check",
        choices=["all", "process-isolation", "renderer-stateless", "zero-allocation", "ipc-safety"],
        default="all",
        help="Specific boundary check to run (default: all)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    violations = audit_all(root)

    category_filter_map = {
        "process-isolation": {
            "forbidden-ipc-primitive",
            "forbidden-global-statement",
            "worker-import-ui",
            "core-import-violation",
            "model-import-violation",
            "ui-import-violation",
            "ui-hardware-instantiation",
        },
        "renderer-stateless": {
            "renderer-stateful-variable",
            "renderer-stateful-method",
            "renderer-forbidden-import",
        },
        "zero-allocation": {
            "zero-allocation-violation",
        },
        "ipc-safety": {
            "ipc-payload-violation",
            "forbidden-ipc-primitive",
        },
    }

    if args.check != "all":
        allowed_cats = category_filter_map.get(args.check, set())
        violations = [v for v in violations if v.category in allowed_cats]

    if not violations:
        if args.check != "all":
            print(f"PASS: Architectural boundary check '{args.check}' passed with zero violations.")
        else:
            print("PASS: All architectural boundaries and process isolation rules are enforced.")
        return 0

    print(f"FAIL: Found {len(violations)} architectural boundary violations ({args.check}):\n")
    by_category: Dict[str, int] = {}
    for v in violations:
        print(f"  {v}")
        by_category[v.category] = by_category.get(v.category, 0) + 1

    print("\nSummary by category:")
    for cat, count in sorted(by_category.items()):
        print(f"  - {cat}: {count}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
