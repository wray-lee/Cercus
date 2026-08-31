"""Tests for ExperimentController.build_config().

Seam: build_config(form_values) → dict
Pure function — takes a flat dict of form field values (strings/bools),
returns the experiment config dict consumed by stimulus_worker.
"""
import os
import pytest

from src.ui.controller import ExperimentController


def _base_form() -> dict:
    """Minimal valid form values matching LoomingParadigm defaults."""
    return {
        "paradigm": "SingleLooming",
        "pattern": "Left-Right",
        "subject_id": "cricket_test_001",
        "session_start": "1",
        "session_total": "5",
        "iti_range": "60-90",
        "isi_range": "300-300",
        "serial_port": "mock",
        "screen_id": "1",
        "debug": True,
        "viewing_distance_cm": "30.0",
        "screen_width_cm": "53.0",
        "resolution": "3840, 1080",
    }


def test_build_config_returns_all_fixed_keys():
    cfg = ExperimentController.build_config(_base_form())
    expected_keys = {
        "Subject ID", "Session Number", "Total Sessions",
        "ITI Range (sec)", "ISI Range (sec)", "Experiment Pattern",
        "Paradigm Class", "Serial Port", "Stimulus Screen ID",
        "Debug Mode", "Viewing Distance (cm)", "Screen Width (cm)",
        "Screen Width (px)", "Screen Height (px)", "Sync Topology",
        "_output_dir",
    }
    assert expected_keys.issubset(cfg.keys())


def test_build_config_subject_id():
    form = _base_form()
    form["subject_id"] = "  my_cricket  "
    cfg = ExperimentController.build_config(form)
    assert cfg["Subject ID"] == "my_cricket"


def test_build_config_resolution_parsing():
    form = _base_form()
    form["resolution"] = "1920, 1080"
    cfg = ExperimentController.build_config(form)
    assert cfg["Screen Width (px)"] == 1920
    assert cfg["Screen Height (px)"] == 1080


def test_build_config_resolution_single_value():
    form = _base_form()
    form["resolution"] = "2560"
    cfg = ExperimentController.build_config(form)
    assert cfg["Screen Width (px)"] == 2560
    assert cfg["Screen Height (px)"] == 1080  # default


def test_build_config_manual_mode_sets_total_minus_one():
    form = _base_form()
    form["paradigm_params"] = {"Execution Mode": "Manual"}
    cfg = ExperimentController.build_config(form)
    assert cfg["Total Sessions"] == -1


def test_build_config_auto_mode_uses_session_total():
    form = _base_form()
    form["session_total"] = "10"
    form["paradigm_params"] = {"Execution Mode": "Auto"}
    cfg = ExperimentController.build_config(form)
    assert cfg["Total Sessions"] == 10


def test_build_config_merges_paradigm_params():
    form = _base_form()
    form["paradigm_params"] = {"Speed (deg/s)": 42.0, "Size (deg)": 10.0}
    cfg = ExperimentController.build_config(form)
    assert cfg["Speed (deg/s)"] == 42.0
    assert cfg["Size (deg)"] == 10.0


def test_build_config_output_dir_exists():
    cfg = ExperimentController.build_config(_base_form())
    assert os.path.isdir(cfg["_output_dir"])


def test_build_config_safe_int_fallback():
    form = _base_form()
    form["session_start"] = "not_a_number"
    cfg = ExperimentController.build_config(form)
    assert cfg["Session Number"] == 1  # default fallback


def test_build_config_safe_float_fallback():
    form = _base_form()
    form["viewing_distance_cm"] = "bad"
    cfg = ExperimentController.build_config(form)
    assert cfg["Viewing Distance (cm)"] == 30.0  # default fallback
