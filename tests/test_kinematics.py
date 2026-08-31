"""Tests for KinematicEngine — trigger evaluation, speed handling.

Seam: KinematicEngine.evaluate_trigger / update
"""
import pytest

from src.core.kinematics import KinematicEngine


def _make_engine():
    eng = KinematicEngine()
    eng.reset()
    return eng


def test_displacement_trigger():
    eng = _make_engine()
    # Feed enough displacement to exceed threshold
    eng.update(0.0, 0.0, 0.0, 0.0)  # baseline
    eng.update(0.05, 5.0, 0.0, 0.0)
    eng.update(0.10, 5.0, 0.0, 0.0)
    eng.update(0.15, 5.0, 0.0, 0.0)
    assert eng.evaluate_trigger(threshold_dist=10.0, threshold_angle=0.0)


def test_angle_trigger():
    eng = _make_engine()
    eng._cum_dz = 50.0
    assert eng.evaluate_trigger(threshold_dist=0.0, threshold_angle=45.0)


def test_instantaneous_speed_trigger_motion():
    """B3: speed_duration_ms=0.0 with threshold_speed > 0 should check
    instantaneous speed and return True when speed >= threshold."""
    eng = _make_engine()
    # Feed data to build up speed
    eng.update(0.0, 0.0, 0.0, 0.0)  # baseline
    eng.update(0.05, 10.0, 0.0, 0.0)
    eng.update(0.10, 10.0, 0.0, 0.0)
    # After buffering, move_speed should be > 0
    # Force-set for deterministic test
    eng._move_speed = 100.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=50.0, speed_duration_ms=0.0,
    )
    assert result is True


def test_instantaneous_speed_trigger_below_threshold():
    """B3: speed_duration_ms=0.0 — should return False when speed < threshold."""
    eng = _make_engine()
    eng._move_speed = 10.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=50.0, speed_duration_ms=0.0,
    )
    assert result is False


def test_instantaneous_stationary_trigger():
    """B3: speed_duration_ms=0.0 with threshold_speed=0.0 checks stationarity."""
    eng = _make_engine()
    eng._move_speed = 5.0  # below quiet threshold of 15.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=0.0, speed_duration_ms=0.0,
    )
    assert result is True


def test_instantaneous_stationary_trigger_moving():
    """B3: stationary trigger returns False when subject is moving."""
    eng = _make_engine()
    eng._move_speed = 50.0  # above quiet threshold
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=0.0, speed_duration_ms=0.0,
    )
    assert result is False


def test_speed_disabled_by_default():
    """threshold_speed=-1.0 (default) disables speed trigger."""
    eng = _make_engine()
    eng._move_speed = 999.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=-1.0, speed_duration_ms=0.0,
    )
    assert result is False


def test_duration_speed_trigger():
    """Duration-gated speed trigger works when elapsed >= duration."""
    eng = _make_engine()
    eng._move_speed = 100.0
    eng._speed_above_since = 0.0
    eng._last_t = 0.5  # 500ms elapsed
    eng._speed_threshold_active = 50.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=50.0, speed_duration_ms=200.0,
    )
    assert result is True


def test_no_trigger_when_all_disabled():
    eng = _make_engine()
    assert eng.evaluate_trigger(0.0, 0.0) is False
