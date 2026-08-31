"""Documentation-to-Code Alignment Auditor for Cercus.

Audits:
1. Maps each term in CONTEXT.md Section 2 to actual Python classes and files.
2. Verifies topology diagram accuracy in CONTEXT.md Section 3 (mp.Queue names, process structure).
3. Checks that docs/adr/ exists, is non-empty, and contains valid ADR documents.
"""

import ast
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


class DocViolation:
    """Represents a documentation-code alignment violation."""

    def __init__(self, doc_file: str, line: int, category: str, message: str) -> None:
        """Initialize documentation violation."""
        self.doc_file = doc_file
        self.line = line
        self.category = category
        self.message = message

    def __str__(self) -> str:
        """Format violation as human-readable string."""
        return f"{self.doc_file}:{self.line} [{self.category}] {self.message}"


class DocsAuditor:
    """Auditor for documentation-code alignment and ADR verification."""

    EXPECTED_SECTION_2_TERMS: Dict[str, Dict[str, str]] = {
        "Paradigm": {
            "file": "src/models/paradigm.py",
            "class": "BaseParadigm",
            "required_subclasses": "LoomingParadigm,OpticFlowParadigm,MovementTraceParadigm",
        },
        "Trial / Session": {
            "file": "src/workers/stimulus_worker.py",
            "class": "GenericWorker",
        },
        "Kinematics / KinematicEngine": {
            "file": "src/core/kinematics.py",
            "class": "KinematicEngine",
        },
        "Hardware / SerialDaemon": {
            "file": "src/core/hardware.py",
            "class": "SerialDaemon",
        },
        "CoreRenderer": {
            "file": "src/core/render.py",
            "class": "CoreRenderer",
        },
        "Worker Process": {
            "file": "src/workers/stimulus_worker.py",
            "class": "GenericWorker",
            "alt_file": "src/workers/calibration_worker.py",
            "alt_class": "CalibrationWorker",
        },
        "ExperimentController": {
            "file": "src/ui/controller.py",
            "class": "ExperimentController",
        },
        "AppState": {
            "file": "src/ui/state.py",
            "class": "AppState",
        },
        "Dashboard": {
            "file": "src/ui/pages/dashboard.py",
            "function": "build_dashboard",
        },
        "Monitor": {
            "file": "src/ui/pages/monitor.py",
            "function": "build_monitor",
        },
        "Verdict": {
            "file": "src/models/paradigm.py",
            "class": "BaseParadigm",
            "method": "classify_response",
        },
    }

    REQUIRED_ADR_SECTIONS: List[str] = [
        "## Status",
        "## Context",
        "## Decision",
        "## Consequences",
    ]

    def __init__(self, root_dir: Path) -> None:
        """Initialize docs auditor with repository root directory."""
        self.root_dir = root_dir.resolve()
        self.context_path = self.root_dir / "CONTEXT.md"
        self.adr_dir = self.root_dir / "docs" / "adr"
        self.violations: List[DocViolation] = []

    def audit(self) -> List[DocViolation]:
        """Run full documentation audit suite."""
        self.violations.clear()
        self.audit_context_file()
        self.audit_adr_directory()
        return self.violations

    def audit_context_file(self) -> None:
        """Audit CONTEXT.md Section 2 ubiquitous language and Section 3 topology."""
        if not self.context_path.is_file():
            self.violations.append(
                DocViolation(
                    str(self.context_path),
                    1,
                    "missing-file",
                    "CONTEXT.md not found at repo root.",
                )
            )
            return

        try:
            content = self.context_path.read_text(encoding="utf-8")
        except Exception as e:
            self.violations.append(
                DocViolation(str(self.context_path), 1, "read-error", str(e))
            )
            return

        lines = content.splitlines()
        self._audit_section_2_terms(lines)
        self._audit_section_3_topology(lines, content)

    def _audit_section_2_terms(self, lines: List[str]) -> None:
        """Verify each term in Section 2 table maps to actual Python code."""
        in_section_2 = False
        terms_found: Set[str] = set()

        for idx, line in enumerate(lines, start=1):
            if line.strip().startswith("## 2."):
                in_section_2 = True
                continue
            if in_section_2 and line.strip().startswith("## 3."):
                break
            if not in_section_2 or not line.strip().startswith("|"):
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue

            raw_term = parts[1].replace("*", "").strip()
            definition = parts[2].strip()

            if not raw_term or raw_term == "Term" or raw_term.startswith(":--"):
                continue

            terms_found.add(raw_term)

            # Check for obsolete engine references
            if "pygame" in definition.lower():
                self.violations.append(
                    DocViolation(
                        "CONTEXT.md",
                        idx,
                        "outdated-term-definition",
                        f"Term '{raw_term}' refers to 'Pygame' which is obsolete (PsychoPy is used).",
                    )
                )

            # Verify against expected Python classes/functions
            expected = self.EXPECTED_SECTION_2_TERMS.get(raw_term)
            if not expected:
                self.violations.append(
                    DocViolation(
                        "CONTEXT.md",
                        idx,
                        "unknown-term",
                        f"Term '{raw_term}' has no verification spec in DocsAuditor.",
                    )
                )
                continue

            self._verify_term_binding(raw_term, expected, idx)

        # Check for missing terms in documentation
        for term in self.EXPECTED_SECTION_2_TERMS:
            if term not in terms_found:
                self.violations.append(
                    DocViolation(
                        "CONTEXT.md",
                        1,
                        "missing-term",
                        f"Expected term '{term}' is missing from CONTEXT.md Section 2.",
                    )
                )

    def _verify_term_binding(
        self, term: str, expected: Dict[str, str], line_no: int
    ) -> None:
        """Verify that the mapped Python class, function, or method exists."""
        rel_file = expected["file"]
        target_file = self.root_dir / rel_file

        if not target_file.is_file():
            self.violations.append(
                DocViolation(
                    "CONTEXT.md",
                    line_no,
                    "broken-file-reference",
                    f"Term '{term}' references '{rel_file}', which does not exist.",
                )
            )
            return

        try:
            tree = ast.parse(target_file.read_text(encoding="utf-8"), filename=str(target_file))
        except Exception as e:
            self.violations.append(
                DocViolation(
                    rel_file,
                    1,
                    "ast-parse-error",
                    f"Failed to parse '{rel_file}' for term '{term}': {e}",
                )
            )
            return

        # Check target class
        target_class = expected.get("class")
        if target_class:
            class_node = next(
                (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == target_class),
                None,
            )
            if not class_node:
                self.violations.append(
                    DocViolation(
                        "CONTEXT.md",
                        line_no,
                        "missing-class",
                        f"Term '{term}' references class '{target_class}' in '{rel_file}', but it was not found.",
                    )
                )
            else:
                # Check method inside class if specified
                target_method = expected.get("method")
                if target_method:
                    method_node = next(
                        (
                            node
                            for node in class_node.body
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and node.name == target_method
                        ),
                        None,
                    )
                    if not method_node:
                        self.violations.append(
                            DocViolation(
                                "CONTEXT.md",
                                line_no,
                                "missing-method",
                                f"Term '{term}' references method '{target_method}' in '{target_class}', but it was not found.",
                            )
                        )

        # Check target function
        target_func = expected.get("function")
        if target_func:
            func_node = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == target_func
                ),
                None,
            )
            if not func_node:
                self.violations.append(
                    DocViolation(
                        "CONTEXT.md",
                        line_no,
                        "missing-function",
                        f"Term '{term}' references function '{target_func}' in '{rel_file}', but it was not found.",
                    )
                )

        # Check required subclasses
        required_subs = expected.get("required_subclasses")
        if required_subs:
            sub_names = [s.strip() for s in required_subs.split(",")]
            found_classes = {
                node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            }
            for sub in sub_names:
                if sub not in found_classes:
                    self.violations.append(
                        DocViolation(
                            "CONTEXT.md",
                            line_no,
                            "missing-subclass",
                            f"Term '{term}' requires subclass '{sub}' in '{rel_file}', but it was not found.",
                        )
                    )

    def _audit_section_3_topology(self, lines: List[str], full_content: str) -> None:
        """Verify architectural topology diagram accuracy."""
        # Check IPC Queue names
        if "cmd_queue" not in full_content or "telemetry_queue" not in full_content:
            self.violations.append(
                DocViolation(
                    "CONTEXT.md",
                    31,
                    "topology-missing-queues",
                    "Topology diagram must explicitly document 'cmd_queue' and 'telemetry_queue'.",
                )
            )

        # Check process structure
        required_topology_elements = [
            ("Main UI Process", "UI Process boundary"),
            ("Worker Process", "Worker Process boundary"),
            ("ExperimentController", "UI Controller component"),
            ("AppState", "Reactive AppState component"),
            ("SerialDaemon", "Worker Hardware interface"),
            ("KinematicEngine", "Worker Kinematic engine"),
            ("CoreRenderer", "Worker Rendering engine"),
        ]

        for element, desc in required_topology_elements:
            if element not in full_content:
                self.violations.append(
                    DocViolation(
                        "CONTEXT.md",
                        31,
                        "topology-missing-element",
                        f"Topology diagram missing {desc} ('{element}').",
                    )
                )

        # Check for obsolete engine references in topology diagram
        if "pygame" in full_content.lower():
            self.violations.append(
                DocViolation(
                    "CONTEXT.md",
                    31,
                    "topology-outdated-tech",
                    "Topology diagram mentions 'Pygame' which is obsolete (PsychoPy is used).",
                )
            )

    def audit_adr_directory(self) -> None:
        """Check that docs/adr/ exists, is non-empty, and has valid ADR structure."""
        if not self.adr_dir.exists():
            self.violations.append(
                DocViolation(
                    "docs/adr",
                    1,
                    "missing-adr-directory",
                    "Directory 'docs/adr/' does not exist.",
                )
            )
            return

        if not self.adr_dir.is_dir():
            self.violations.append(
                DocViolation(
                    "docs/adr",
                    1,
                    "invalid-adr-directory",
                    "'docs/adr' exists but is not a directory.",
                )
            )
            return

        adr_files = sorted(self.adr_dir.glob("*.md"))
        if not adr_files:
            self.violations.append(
                DocViolation(
                    "docs/adr",
                    1,
                    "empty-adr-directory",
                    "Directory 'docs/adr/' is empty. Must contain Architecture Decision Records.",
                )
            )
            return

        for adr_path in adr_files:
            self._audit_single_adr(adr_path)

    def _audit_single_adr(self, adr_path: Path) -> None:
        """Validate structure and completeness of a single ADR file."""
        rel_path = f"docs/adr/{adr_path.name}"
        try:
            content = adr_path.read_text(encoding="utf-8")
        except Exception as e:
            self.violations.append(
                DocViolation(rel_path, 1, "read-error", str(e))
            )
            return

        if not content.strip():
            self.violations.append(
                DocViolation(rel_path, 1, "empty-adr-file", f"ADR file '{adr_path.name}' is empty.")
            )
            return

        # Check title format (# ADR ...)
        if not re.search(r"^#\s+ADR\s+\d+:", content, re.MULTILINE):
            self.violations.append(
                DocViolation(
                    rel_path,
                    1,
                    "invalid-adr-title",
                    f"ADR '{adr_path.name}' missing title formatted as '# ADR <number>: <Title>'.",
                )
            )

        # Check required sections
        for section in self.REQUIRED_ADR_SECTIONS:
            if section not in content:
                self.violations.append(
                    DocViolation(
                        rel_path,
                        1,
                        "missing-adr-section",
                        f"ADR '{adr_path.name}' missing required section '{section}'.",
                    )
                )


def audit_docs(root_dir: Path) -> List[DocViolation]:
    """Audit repository documentation against code alignment and ADR standards."""
    auditor = DocsAuditor(root_dir)
    return auditor.audit()


def main() -> int:
    """CLI entrypoint for documentation alignment auditor."""
    root = Path(__file__).resolve().parent.parent
    violations = audit_docs(root)

    if not violations:
        print("PASS: Documentation is aligned with codebase and ADRs are valid.")
        return 0

    print(f"FAIL: Found {len(violations)} documentation-code alignment violations:\n")
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
