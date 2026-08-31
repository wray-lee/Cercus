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


def test_safe_int_with_int_and_float():
    from src.ui.controller import _safe_int
    assert _safe_int(10, 1) == 10
    assert _safe_int(10.5, 1) == 10
    assert _safe_int("10", 1) == 10
    assert _safe_int("invalid", 1) == 1


def test_safe_int_nan_inf_fallback():
    """_safe_int must not crash on float('nan') or float('inf')."""
    from src.ui.controller import _safe_int
    assert _safe_int(float('nan'), 99) == 99
    assert _safe_int(float('inf'), 99) == 99
    assert _safe_int(float('-inf'), 99) == 99


def test_safe_int_bool_returns_default():
    """_safe_int should not coerce True/False to 1/0."""
    from src.ui.controller import _safe_int
    assert _safe_int(True, 42) == 42
    assert _safe_int(False, 42) == 42


def test_safe_float_with_various_inputs():
    """_safe_float must handle bool, nan, inf, valid string, invalid string."""
    from src.ui.controller import _safe_float
    assert _safe_float("3.14", 10.0) == 3.14
    assert _safe_float("invalid", 10.0) == 10.0
    assert _safe_float(True, 10.0) == 10.0
    assert _safe_float(False, 10.0) == 10.0
    assert _safe_float(float('nan'), 10.0) == 10.0
    assert _safe_float(float('inf'), 10.0) == 10.0
    assert _safe_float(float('-inf'), 10.0) == 10.0


def test_coerce_params_nan_and_inf():
    from src.ui.controller import _coerce_params
    schema = {
        "int_param": {"type": "int", "default": 10, "min": 0, "max": 100},
        "float_param": {"type": "float", "default": 5.5, "min": 0.0, "max": 50.0},
    }
    params = {
        "int_param": float("nan"),
        "float_param": float("inf"),
    }
    res = _coerce_params(params, schema)
    assert res["int_param"] == 10
    assert res["float_param"] == 5.5


def test_global_poll_terminal_status_protection(monkeypatch):
    from src.ui.app import _global_poll, controller, state

    # Reset controller & state
    controller.terminal_status = "worker_done"
    controller.terminal_error = ""
    state.worker_died = True
    state.worker_status = "worker_done"

    # Mock poll_telemetry returning no new terminal event, but worker_died = True
    monkeypatch.setattr(controller, "poll_telemetry", lambda: {
        "telemetry": None, "verdicts": [], "terminal": None, "worker_died": True
    })
    monkeypatch.setattr(controller, "cleanup_worker", lambda: None)

    _global_poll()

    # Existing worker_done should be preserved, not overwritten with worker_error
    assert controller.terminal_status == "worker_done"
    assert state.worker_status == "worker_done"


def test_global_poll_terminal_before_worker_died(monkeypatch):
    from src.ui.app import _global_poll, controller, state

    controller.terminal_status = None
    controller.terminal_error = ""
    state.worker_died = False
    state.worker_status = "idle"

    # Step 1: terminal event received while worker process is still alive
    monkeypatch.setattr(controller, "poll_telemetry", lambda: {
        "telemetry": None, "verdicts": [],
        "terminal": {"action": "worker_done", "error": ""},
        "worker_died": False,
    })
    _global_poll()

    assert controller.terminal_status == "worker_done"
    assert state.worker_status == "worker_done"

    # Step 2: Next poll tick — terminal event is None, worker_died becomes True
    monkeypatch.setattr(controller, "poll_telemetry", lambda: {
        "telemetry": None, "verdicts": [], "terminal": None, "worker_died": True
    })
    monkeypatch.setattr(controller, "cleanup_worker", lambda: None)
    _global_poll()

    assert controller.terminal_status == "worker_done"
    assert state.worker_status == "worker_done"



