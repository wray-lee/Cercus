"""Tests for AppState.apply() — telemetry event consumer.

Seam: AppState.apply(poll_result) → updates reactive state fields
"""
import pytest

from src.ui.state import AppState


def test_apply_telemetry_updates_phase():
    s = AppState()
    s.apply({"telemetry": {"action": "telemetry", "phase": "ITI", "ui_color": "cyan",
             "session_num": 1, "trial_idx": 2, "total_trials": 10,
             "ui_metrics": {"pos_x": 1.0, "pos_y": 2.0, "k_angle": 45.0}},
             "verdicts": [], "terminal": None, "worker_died": False})
    assert s.phase == "ITI"
    assert s.ui_color == "cyan"
    assert s.session_num == 1
    assert s.trial_idx == 2


def test_apply_verdict_appends():
    s = AppState()
    s.apply({"telemetry": None, "terminal": None, "worker_died": False,
             "verdicts": [{"action": "trial_verdict", "trial_idx": 1,
                           "response": "escape", "cum_disp": 20.0,
                           "cum_dz": 5.0, "peak_speed": 40.0, "side": "L"}]})
    assert len(s.verdict_history) == 1
    assert s.verdict_history[0]["response"] == "escape"


def test_apply_verdict_counts():
    s = AppState()
    s.apply({"telemetry": None, "terminal": None, "worker_died": False,
             "verdicts": [
                 {"response": "escape"},
                 {"response": "startle"},
                 {"response": "no_response"},
                 {"response": "escape"},
             ]})
    assert s.verdict_counts == {"escape": 2, "startle": 1, "no_response": 1}


def test_apply_terminal_done():
    s = AppState()
    s.apply({"telemetry": None, "verdicts": [], "worker_died": False,
             "terminal": {"action": "worker_done"}})
    assert s.worker_status == "worker_done"
    assert s.worker_error == ""


def test_apply_terminal_error():
    s = AppState()
    s.apply({"telemetry": None, "verdicts": [], "worker_died": False,
             "terminal": {"action": "worker_error", "error": "Serial timeout"}})
    assert s.worker_status == "worker_error"
    assert s.worker_error == "Serial timeout"


def test_apply_worker_died():
    s = AppState()
    s.apply({"telemetry": None, "verdicts": [], "terminal": None,
             "worker_died": True})
    assert s.worker_died is True


def test_apply_session_change_clears_verdicts():
    s = AppState()
    s.apply({"telemetry": {"action": "telemetry", "phase": "ITI",
             "session_num": 1, "ui_metrics": {}},
             "verdicts": [{"response": "escape"}],
             "terminal": None, "worker_died": False})
    assert len(s.verdict_history) == 1
    # Session changes
    s.apply({"telemetry": {"action": "telemetry", "phase": "ITI",
             "session_num": 2, "ui_metrics": {}},
             "verdicts": [], "terminal": None, "worker_died": False})
    assert len(s.verdict_history) == 0
    assert s.verdict_counts == {"escape": 0, "startle": 0, "no_response": 0}


def test_apply_trajectory_updates():
    s = AppState()
    s.apply({"telemetry": {"action": "telemetry", "phase": "Kinematic",
             "ui_metrics": {"pos_x": 5.0, "pos_y": 10.0, "k_angle": 30.0,
                            "k_turn_speed": 2.5, "k_disp": 7.0}},
             "verdicts": [], "terminal": None, "worker_died": False})
    assert len(s.trail_points) == 1
    assert s.trail_points[0] == (5.0, 10.0)
    assert s.trail_angle == 30.0
    assert s.kinematic["k_angle"] == 30.0


def test_apply_trajectory_monotonic_bbox():
    s = AppState()
    for x, y in [(0, 0), (10, 10), (5, 5)]:
        s.apply({"telemetry": {"action": "telemetry", "phase": "Kinematic",
                 "ui_metrics": {"pos_x": float(x), "pos_y": float(y)}},
                 "verdicts": [], "terminal": None, "worker_died": False})
    assert s.trail_bbox == (0.0, 10.0, 0.0, 10.0)  # never shrinks


def test_reset_clears_all():
    s = AppState()
    s.apply({"telemetry": {"action": "telemetry", "phase": "ITI",
             "session_num": 1, "ui_metrics": {"pos_x": 1.0, "pos_y": 2.0}},
             "verdicts": [{"response": "escape"}],
             "terminal": None, "worker_died": False})
    s.reset()
    assert s.phase == "IDLE"
    assert len(s.trail_points) == 0
    assert len(s.verdict_history) == 0
    assert s.worker_status == "idle"
