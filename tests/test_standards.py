"""Tests for codebase standards compliance and AST audit tool.

Seam: scripts/audit_standards.py -> StandardsAuditor, audit_all
"""
from pathlib import Path

from scripts.audit_standards import StandardsAuditor, audit_all


def test_code_standards_compliance() -> None:
    """Ensure entire Cercus codebase has 0 compliance violations."""
    root_dir = Path(__file__).resolve().parent.parent
    violations = audit_all(root_dir)
    error_msgs = [str(v) for v in violations]
    assert len(violations) == 0, f"Found {len(violations)} violations:\n" + "\n".join(error_msgs)


def test_auditor_detects_relative_import() -> None:
    """Auditor must detect relative imports."""
    code = "from .sibling import something\n"
    auditor = StandardsAuditor("dummy.py", code)
    violations = auditor.audit()
    assert any(v.category == "relative-import" for v in violations)


def test_auditor_detects_wildcard_import() -> None:
    """Auditor must detect wildcard imports."""
    code = "from math import *\n"
    auditor = StandardsAuditor("dummy.py", code)
    violations = auditor.audit()
    assert any(v.category == "wildcard-import" for v in violations)


def test_auditor_detects_missing_class_docstring() -> None:
    """Auditor must detect missing class docstrings."""
    code = "class Undocumented:\n    pass\n"
    auditor = StandardsAuditor("dummy.py", code)
    violations = auditor.audit()
    assert any(v.category == "missing-class-docstring" for v in violations)


def test_auditor_detects_missing_type_hints() -> None:
    """Auditor must detect missing parameter and return type hints."""
    code = "def untyped_func(x):\n    return x\n"
    auditor = StandardsAuditor("dummy.py", code)
    violations = auditor.audit()
    assert any(v.category == "missing-return-type" for v in violations)
    assert any(v.category == "missing-param-type" for v in violations)


def test_auditor_detects_import_order_violation() -> None:
    """Auditor must detect stdlib imported after third-party modules."""
    code = "import numpy as np\nimport math\n"
    auditor = StandardsAuditor("dummy.py", code)
    violations = auditor.audit()
    assert any(v.category == "import-order" for v in violations)
