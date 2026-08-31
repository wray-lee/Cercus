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


def test_peak_move_speed_tracking():
    """peak_move_speed must track the max move_speed reached even if speed drops later."""
    eng = _make_engine()
    assert hasattr(eng, "peak_move_speed")
    assert eng.peak_move_speed == 0.0

    # Step 1: baseline
    eng.update(0.0, 0.0, 0.0, 0.0)
    # Step 2: high speed movement (dx=10mm over 10ms = 1000 mm/s)
    eng.update(0.010, 10.0, 0.0, 0.0)
    high_peak = eng.peak_move_speed
    assert high_peak > 0.0

    # Step 3: slow movement (dx=1mm over 10ms = 100 mm/s)
    eng.update(0.020, 1.0, 0.0, 0.0)
    assert eng.move_speed < high_peak
    # peak_move_speed must stay at high_peak
    assert eng.peak_move_speed == high_peak

    # Reset clears peak_move_speed
    eng.reset()
    assert eng.peak_move_speed == 0.0


def test_buf_dt_5ms_threshold():
    """Speed calculations should update when accumulated dt >= 5ms (0.005s)."""
    eng = _make_engine()
    eng.update(0.0, 0.0, 0.0, 0.0)
    # 10ms step (> 5ms but < 30ms)
    eng.update(0.010, 10.0, 0.0, 0.0)
    # Speed should be calculated (non-zero move_speed)
    assert eng.move_speed > 0.0


def test_effective_speed_returns_peak_when_nonzero():
    """effective_speed returns peak_move_speed when it > 0."""
    eng = _make_engine()
    eng._peak_move_speed = 200.0
    eng._move_speed = 50.0
    assert eng.effective_speed == 200.0


def test_effective_speed_falls_back_to_move_speed():
    """effective_speed returns move_speed when peak is 0."""
    eng = _make_engine()
    eng._peak_move_speed = 0.0
    eng._move_speed = 42.0
    assert eng.effective_speed == 42.0


def test_quiet_speed_threshold_is_class_constant():
    """QUIET_SPEED_THRESHOLD is accessible and used by stationary trigger."""
    assert hasattr(KinematicEngine, 'QUIET_SPEED_THRESHOLD')
    assert KinematicEngine.QUIET_SPEED_THRESHOLD == 10.0


def test_quiet_speed_threshold_used_in_update_method():
    """Verify QUIET_SPEED_THRESHOLD is used in update() stationary tracking, not hardcoded."""
    import inspect
    source = inspect.getsource(KinematicEngine.update)
    # Should NOT contain hardcoded 15.0 (only QUIET_SPEED_THRESHOLD)
    assert "15.0" not in source, "update() contains hardcoded 15.0 instead of QUIET_SPEED_THRESHOLD"
    assert "QUIET_SPEED_THRESHOLD" in source or "_speed_threshold_active" in source

