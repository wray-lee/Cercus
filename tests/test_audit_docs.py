"""Tests for documentation-to-code alignment and ADR verification auditor.

Seam: scripts/audit_docs.py -> DocsAuditor, audit_docs
"""
import tempfile
from pathlib import Path

from scripts.audit_docs import DocsAuditor, audit_docs


def test_docs_alignment_compliance() -> None:
    """Ensure entire Cercus documentation has 0 alignment and ADR violations."""
    root_dir = Path(__file__).resolve().parent.parent
    violations = audit_docs(root_dir)
    error_msgs = [str(v) for v in violations]
    assert len(violations) == 0, f"Found {len(violations)} doc violations:\n" + "\n".join(error_msgs)


def test_auditor_detects_missing_context() -> None:
    """Auditor must detect missing CONTEXT.md file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "missing-file" for v in violations)


def test_auditor_detects_outdated_pygame_term() -> None:
    """Auditor must detect obsolete references like Pygame in term definitions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text(
            "# Title\n## 2. Ubiquitous Language\n| Term | Definition |\n| :--- | :--- |\n"
            "| **CoreRenderer** | Drawing engine mapping to Pygame surfaces. |\n"
            "## 3. Topology\ncmd_queue telemetry_queue Main UI Process Worker Process "
            "ExperimentController AppState SerialDaemon KinematicEngine CoreRenderer\n",
            encoding="utf-8",
        )
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-test.md").write_text(
            "# ADR 0001: Test\n## Status\nAccepted\n## Context\nC\n## Decision\nD\n## Consequences\nE\n",
            encoding="utf-8",
        )

        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "outdated-term-definition" for v in violations)


def test_auditor_detects_missing_adr_directory() -> None:
    """Auditor must detect missing docs/adr directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        context_file = tmp_path / "CONTEXT.md"
        context_file.write_text("# Title\n", encoding="utf-8")

        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "missing-adr-directory" for v in violations)


def test_auditor_detects_empty_adr_file() -> None:
    """Auditor must detect empty ADR files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "CONTEXT.md").write_text("# Title\n", encoding="utf-8")
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-empty.md").write_text("   \n", encoding="utf-8")

        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "empty-adr-file" for v in violations)


def test_auditor_detects_missing_adr_section() -> None:
    """Auditor must detect ADR files missing mandatory sections."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "CONTEXT.md").write_text("# Title\n", encoding="utf-8")
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-incomplete.md").write_text(
            "# ADR 0001: Incomplete\n## Status\nAccepted\n## Context\nSome context\n",
            encoding="utf-8",
        )

        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "missing-adr-section" for v in violations)


def test_auditor_detects_obsolete_port_8080() -> None:
    """Auditor must detect references to obsolete port 8080 across documentation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "CONTEXT.md").write_text(
            "# Title\n## 2. Ubiquitous Language\n| Term | Definition |\n| :--- | :--- |\n"
            "| **CoreRenderer** | Stateless drawing engine. |\n"
            "## 3. Topology\ncmd_queue telemetry_queue Main UI Process Worker Process "
            "ExperimentController AppState SerialDaemon KinematicEngine CoreRenderer\n",
            encoding="utf-8",
        )
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-test.md").write_text(
            "# ADR 0001: Test\n## Status\nAccepted\n## Context\nC\n## Decision\nD\n## Consequences\nE\n",
            encoding="utf-8",
        )
        readme = tmp_path / "README.md"
        readme.write_text("Monitor is at http://localhost:8080/monitor\n", encoding="utf-8")

        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "outdated-port" for v in violations)


def test_auditor_detects_boundary_signature_drift() -> None:
    """Auditor must detect obsolete 4-tuple or List[int] return signatures in src/models/BOUNDARY.md."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "CONTEXT.md").write_text(
            "# Title\n## 2. Ubiquitous Language\n| Term | Definition |\n| :--- | :--- |\n"
            "| **CoreRenderer** | Stateless drawing engine. |\n"
            "## 3. Topology\ncmd_queue telemetry_queue Main UI Process Worker Process "
            "ExperimentController AppState SerialDaemon KinematicEngine CoreRenderer\n",
            encoding="utf-8",
        )
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-test.md").write_text(
            "# ADR 0001: Test\n## Status\nAccepted\n## Context\nC\n## Decision\nD\n## Consequences\nE\n",
            encoding="utf-8",
        )
        models_dir = tmp_path / "src" / "models"
        models_dir.mkdir(parents=True)
        boundary_md = models_dir / "BOUNDARY.md"
        boundary_md.write_text(
            "# Paradigm Boundary\n"
            "- `process_frame(elapsed_time: float, trial_context: dict, hw_telemetry: dict) -> Tuple[bool, List[dict], dict, List[int]]`\n",
            encoding="utf-8",
        )

        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "outdated-signature" for v in violations)


def test_auditor_detects_obsolete_gui_framework() -> None:
    """Auditor must detect obsolete GUI framework references like CustomTkinter in active docs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "CONTEXT.md").write_text(
            "# Title\n## 2. Ubiquitous Language\n| Term | Definition |\n| :--- | :--- |\n"
            "| **CoreRenderer** | Stateless drawing engine. |\n"
            "## 3. Topology\ncmd_queue telemetry_queue Main UI Process Worker Process "
            "ExperimentController AppState SerialDaemon KinematicEngine CoreRenderer\n",
            encoding="utf-8",
        )
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-test.md").write_text(
            "# ADR 0001: Test\n## Status\nAccepted\n## Context\nC\n## Decision\nD\n## Consequences\nE\n",
            encoding="utf-8",
        )
        docs_dir = tmp_path / "docs"
        (docs_dir / "PRD.md").write_text(
            "# PRD\nDesktop CustomTkinter controls alongside web mirror.\n",
            encoding="utf-8",
        )

        auditor = DocsAuditor(tmp_path)
        violations = auditor.audit()
        assert any(v.category == "outdated-tech-reference" for v in violations)
