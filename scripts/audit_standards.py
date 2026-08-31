"""AST-based code standards compliance auditor for Cercus.

Audits:
1. Absolute imports (no relative imports)
2. No wildcard imports
3. Public function type hints (arguments and return types)
4. Class docstrings
5. Import ordering (stdlib -> third-party -> local)
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# Known stdlib modules fallback for older pythons if sys.stdlib_module_names not present
STDLIB_MODULES: Set[str] = getattr(
    sys,
    "stdlib_module_names",
    {
        "abc", "argparse", "array", "ast", "asyncio", "base64", "collections",
        "contextlib", "copy", "csv", "dataclasses", "datetime", "enum", "errno",
        "functools", "gc", "glob", "hashlib", "importlib", "inspect", "io",
        "itertools", "json", "logging", "math", "multiprocessing", "os",
        "pathlib", "pickle", "platform", "queue", "random", "re", "secrets",
        "shutil", "signal", "socket", "sqlite3", "string", "struct", "subprocess",
        "sys", "tempfile", "threading", "time", "traceback", "types", "typing",
        "unittest", "urllib", "uuid", "warnings", "weakref", "zipfile",
    },
)

LOCAL_PREFIXES: Set[str] = {"src", "tests", "main", "scripts", "test_server"}


def classify_module(mod_name: Optional[str], level: int = 0) -> str:
    """Classify module as 'stdlib', 'third_party', or 'local'."""
    if level > 0:
        return "local"
    if not mod_name:
        return "local"
    top_level = mod_name.split(".")[0]
    if top_level in LOCAL_PREFIXES:
        return "local"
    if top_level in STDLIB_MODULES:
        return "stdlib"
    return "third_party"


class Violation:
    """Represents a code standard violation."""

    def __init__(self, file_path: str, line: int, category: str, message: str) -> None:
        """Initialize violation."""
        self.file_path = file_path
        self.line = line
        self.category = category
        self.message = message

    def __str__(self) -> str:
        """Format violation as string."""
        return f"{self.file_path}:{self.line} [{self.category}] {self.message}"


class StandardsAuditor(ast.NodeVisitor):
    """AST visitor to audit code against Cercus standards."""

    def __init__(self, file_path: str, source_code: str) -> None:
        """Initialize auditor."""
        self.file_path = file_path
        self.source_code = source_code
        self.violations: List[Violation] = []
        self.top_level_imports: List[Tuple[int, str, str]] = []  # (line, group, desc)

    def audit(self) -> List[Violation]:
        """Run AST audit on the file."""
        try:
            tree = ast.parse(self.source_code, filename=self.file_path)
        except SyntaxError as e:
            self.violations.append(
                Violation(self.file_path, e.lineno or 1, "syntax-error", str(e))
            )
            return self.violations

        self.visit(tree)
        self._check_import_order()
        return self.violations

    def visit_Import(self, node: ast.Import) -> None:
        """Check import statement."""
        for alias in node.names:
            group = classify_module(alias.name, 0)
            if node.col_offset == 0:
                self.top_level_imports.append((node.lineno, group, f"import {alias.name}"))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check from ... import statement."""
        # Check relative import
        if node.level > 0:
            dots = "." * node.level
            mod = node.module or ""
            self.violations.append(
                Violation(
                    self.file_path,
                    node.lineno,
                    "relative-import",
                    f"Relative import detected: 'from {dots}{mod} import ...'. Must use absolute import.",
                )
            )

        # Check wildcard import
        for alias in node.names:
            if alias.name == "*":
                self.violations.append(
                    Violation(
                        self.file_path,
                        node.lineno,
                        "wildcard-import",
                        f"Wildcard import forbidden: 'from {node.module} import *'.",
                    )
                )

        group = classify_module(node.module, node.level)
        if node.col_offset == 0:
            self.top_level_imports.append(
                (node.lineno, group, f"from {node.module or ''} import ...")
            )

        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check class docstring and methods."""
        docstring = ast.get_docstring(node)
        if not docstring or not docstring.strip():
            self.violations.append(
                Violation(
                    self.file_path,
                    node.lineno,
                    "missing-class-docstring",
                    f"Class '{node.name}' is missing a docstring.",
                )
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function type hints."""
        self._check_function_hints(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function type hints."""
        self._check_function_hints(node)
        self.generic_visit(node)

    def _check_function_hints(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Check parameters and return annotations for public functions."""
        name = node.name
        # Skip private functions (start with single underscore and not dunder)
        if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
            return

        # Check return type annotation
        # Note: __init__ return type can be omitted or -> None, but standardizing -> None is best
        if node.returns is None:
            self.violations.append(
                Violation(
                    self.file_path,
                    node.lineno,
                    "missing-return-type",
                    f"Public function/method '{name}' is missing a return type hint.",
                )
            )

        # Check parameters
        all_args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
        for i, arg in enumerate(all_args):
            # Skip self/cls for methods
            if i == 0 and arg.arg in ("self", "cls"):
                continue
            if arg.annotation is None:
                self.violations.append(
                    Violation(
                        self.file_path,
                        arg.lineno,
                        "missing-param-type",
                        f"Parameter '{arg.arg}' in public function/method '{name}' is missing type hint.",
                    )
                )

        if node.args.vararg and node.args.vararg.annotation is None:
            self.violations.append(
                Violation(
                    self.file_path,
                    node.args.vararg.lineno,
                    "missing-param-type",
                    f"Vararg '*{node.args.vararg.arg}' in public function/method '{name}' is missing type hint.",
                )
            )

        if node.args.kwarg and node.args.kwarg.annotation is None:
            self.violations.append(
                Violation(
                    self.file_path,
                    node.args.kwarg.lineno,
                    "missing-param-type",
                    f"Kwarg '**{node.args.kwarg.arg}' in public function/method '{name}' is missing type hint.",
                )
            )

    def _check_import_order(self) -> None:
        """Check that top-level imports follow stdlib -> third-party -> local order."""
        if not self.top_level_imports:
            return

        group_weights = {"stdlib": 1, "third_party": 2, "local": 3}
        current_max_weight = 1
        current_max_group = "stdlib"

        for line, group, desc in self.top_level_imports:
            weight = group_weights.get(group, 0)
            if weight < current_max_weight:
                self.violations.append(
                    Violation(
                        self.file_path,
                        line,
                        "import-order",
                        f"Import '{desc}' ({group}) appears after {current_max_group} import. "
                        f"Order must be stdlib -> third-party -> local.",
                    )
                )
            else:
                current_max_weight = weight
                current_max_group = group


def audit_file(file_path: Path) -> List[Violation]:
    """Audit a single python file."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [Violation(str(file_path), 1, "read-error", str(e))]

    auditor = StandardsAuditor(str(file_path), source)
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

    # Also check root-level scripts
    for file_name in ["main.py", "test_server.py"]:
        p = root_dir / file_name
        if p.exists():
            py_files.append(p)

    for py_file in sorted(py_files):
        # Exclude git/worktrees/cache
        rel_str = str(py_file)
        if any(x in rel_str for x in [".claude", ".pio", "__pycache__", ".pytest_cache"]):
            continue
        file_violations = audit_file(py_file)
        violations.extend(file_violations)

    return violations


def main() -> int:
    """CLI entrypoint."""
    root = Path(__file__).resolve().parent.parent
    violations = audit_all(root)

    if not violations:
        print("PASS: All modules comply with code standards.")
        return 0

    print(f"FAIL: Found {len(violations)} code standard violations:\n")
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
