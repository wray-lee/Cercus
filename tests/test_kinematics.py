"""Tests for KinematicEngine — trigger evaluation, speed handling.

Seam: KinematicEngine.evaluate_trigger / update
"""
import pytest

from src.core.kinematics import KinematicEngine


def _make_engine():
    eng = KinematicEngine()
    eng.reset()
    return eng


def test_displacement_trigger() -> None:
    eng = _make_engine()
    # Feed enough displacement to exceed threshold
    eng.update(0.0, 0.0, 0.0, 0.0)  # baseline
    eng.update(0.05, 5.0, 0.0, 0.0)
    eng.update(0.10, 5.0, 0.0, 0.0)
    eng.update(0.15, 5.0, 0.0, 0.0)
    assert eng.evaluate_trigger(threshold_dist=10.0, threshold_angle=0.0)


def test_angle_trigger() -> None:
    eng = _make_engine()
    eng._cum_dz = 50.0
    assert eng.evaluate_trigger(threshold_dist=0.0, threshold_angle=45.0)


def test_instantaneous_speed_trigger_motion() -> None:
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


def test_instantaneous_speed_trigger_below_threshold() -> None:
    """B3: speed_duration_ms=0.0 — should return False when speed < threshold."""
    eng = _make_engine()
    eng._move_speed = 10.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=50.0, speed_duration_ms=0.0,
    )
    assert result is False


def test_instantaneous_stationary_trigger() -> None:
    """B3: speed_duration_ms=0.0 with threshold_speed=0.0 checks stationarity."""
    eng = _make_engine()
    eng._move_speed = 5.0  # below quiet threshold of 15.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=0.0, speed_duration_ms=0.0,
    )
    assert result is True


def test_instantaneous_stationary_trigger_moving() -> None:
    """B3: stationary trigger returns False when subject is moving."""
    eng = _make_engine()
    eng._move_speed = 50.0  # above quiet threshold
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=0.0, speed_duration_ms=0.0,
    )
    assert result is False


def test_speed_disabled_by_default() -> None:
    """threshold_speed=-1.0 (default) disables speed trigger."""
    eng = _make_engine()
    eng._move_speed = 999.0
    result = eng.evaluate_trigger(
        threshold_dist=0.0, threshold_angle=0.0,
        threshold_speed=-1.0, speed_duration_ms=0.0,
    )
    assert result is False


def test_duration_speed_trigger() -> None:
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


def test_no_trigger_when_all_disabled() -> None:
    eng = _make_engine()
    assert eng.evaluate_trigger(0.0, 0.0) is False


def test_peak_move_speed_tracking() -> None:
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


def test_buf_dt_5ms_threshold() -> None:
    """Speed calculations should update when accumulated dt >= 5ms (0.005s)."""
    eng = _make_engine()
    eng.update(0.0, 0.0, 0.0, 0.0)
    # 10ms step (> 5ms but < 30ms)
    eng.update(0.010, 10.0, 0.0, 0.0)
    # Speed should be calculated (non-zero move_speed)
    assert eng.move_speed > 0.0


def test_effective_speed_returns_peak_when_nonzero() -> None:
    """effective_speed returns peak_move_speed when it > 0."""
    eng = _make_engine()
    eng._peak_move_speed = 200.0
    eng._move_speed = 50.0
    assert eng.effective_speed == 200.0


def test_effective_speed_falls_back_to_move_speed() -> None:
    """effective_speed returns move_speed when peak is 0."""
    eng = _make_engine()
    eng._peak_move_speed = 0.0
    eng._move_speed = 42.0
    assert eng.effective_speed == 42.0


def test_quiet_speed_threshold_is_class_constant() -> None:
    """QUIET_SPEED_THRESHOLD is accessible and used by stationary trigger."""
    assert hasattr(KinematicEngine, 'QUIET_SPEED_THRESHOLD')
    assert KinematicEngine.QUIET_SPEED_THRESHOLD == 10.0


def test_quiet_speed_threshold_used_in_update_method() -> None:
    """Verify QUIET_SPEED_THRESHOLD is used in update() stationary tracking, not hardcoded."""
    import inspect
    source = inspect.getsource(KinematicEngine.update)
    # Should NOT contain hardcoded 15.0 (only QUIET_SPEED_THRESHOLD)
    assert "15.0" not in source, "update() contains hardcoded 15.0 instead of QUIET_SPEED_THRESHOLD"
    assert "QUIET_SPEED_THRESHOLD" in source or "_speed_threshold_active" in source


def test_dt_zero_and_negative_handling() -> None:
    """Edge cases: dt=0 and dt < 0 should invoke error_cb if present and skip speed calculation."""
    errors = []

    def _err_cb(category: str, msg: str, data: object) -> None:
        errors.append((category, msg, data))

    eng = KinematicEngine(error_callback=_err_cb)
    eng.reset()

    # Step 1: baseline sample at t=1.0
    eng.update(1.0, 1.0, 0.0, 0.0)
    assert eng.pos_x == -1.0  # spatial accumulated
    assert len(errors) == 0

    # Step 2: dt = 0.0 (same timestamp)
    eng.update(1.0, 2.0, 0.0, 0.0)
    assert len(errors) == 1
    assert errors[0][0] == "timing_error"
    assert "dt=0.000000 out of range" in errors[0][1]

    # Step 3: dt < 0.0 (backwards clock)
    eng.update(0.5, 1.0, 0.0, 0.0)
    assert len(errors) == 2
    assert errors[1][0] == "timing_error"

    # Step 4: dt > 1.0 (clock jump)
    eng.update(5.0, 1.0, 0.0, 0.0)
    assert len(errors) == 3
    assert errors[2][0] == "timing_error"


def test_nan_inf_none_dirty_data_handling() -> None:
    """Edge cases: NaN, Inf, None, invalid values should be rejected and trigger error_cb."""
    import math

    errors = []

    def _err_cb(category: str, msg: str, data: object) -> None:
        errors.append((category, msg, data))

    eng = KinematicEngine(error_callback=_err_cb)
    eng.reset()

    # NaN in dx
    eng.update(1.0, math.nan, 0.0, 0.0)
    assert len(errors) == 1
    assert errors[0][0] == "data_anomaly"
    assert errors[0][1] == "non-finite telemetry value"
    assert eng.cum_disp == 0.0

    # Inf in t
    eng.update(float("inf"), 1.0, 0.0, 0.0)
    assert len(errors) == 2
    assert errors[1][0] == "data_anomaly"

    # None or non-float
    eng.update(1.0, None, 0.0, 0.0)  # type: ignore
    assert len(errors) == 3
    assert errors[2][0] == "data_anomaly"


def test_spike_guard_rejection() -> None:
    """Out-of-range per-frame spikes (>30 deg or >20mm) must be rejected."""
    errors = []

    def _err_cb(category: str, msg: str, data: object) -> None:
        errors.append((category, msg, data))

    eng = KinematicEngine(error_callback=_err_cb)
    eng.reset()

    # Normal baseline
    eng.update(0.0, 0.0, 0.0, 0.0)

    # Spike in dx (> 20mm)
    eng.update(0.01, 25.0, 0.0, 0.0)
    assert len(errors) == 1
    assert errors[0][0] == "data_anomaly"
    assert errors[0][1] == "out-of-range telemetry sample"
    assert eng.cum_disp == 0.0

    # Spike in dy (> 20mm)
    eng.update(0.02, 0.0, 25.0, 0.0)
    assert len(errors) == 2

    # Spike in dz (> 30 deg arc, radius=30mm => 30mm * radians(30) ≈ 15.7mm -> dz=20mm gives >38 deg)
    eng.update(0.03, 0.0, 0.0, 20.0)
    assert len(errors) == 3


def test_sustained_speed_tracking_stationary_and_motion() -> None:
    """Verify sustained speed state updates in update() for stationary and motion thresholds."""
    eng = _make_engine()

    # 1. Activate stationary trigger tracking
    assert eng.evaluate_trigger(threshold_dist=0.0, threshold_angle=0.0, threshold_speed=0.0, speed_duration_ms=100.0) is False
    assert eng._speed_threshold_active == 0.0

    # Update with low speed (< QUIET_SPEED_THRESHOLD = 10.0)
    eng.update(0.0, 0.0, 0.0, 0.0)
    eng.update(0.010, 0.01, 0.0, 0.0)  # speed = 1.0 units/sec
    assert eng._speed_above_since == 0.010

    # Update with high speed (> 10.0) -> resets timer
    eng.update(0.020, 0.5, 0.0, 0.0)  # speed = 50.0 units/sec
    assert eng._speed_above_since == -1.0

    # 2. Activate motion trigger tracking
    assert eng.evaluate_trigger(threshold_dist=0.0, threshold_angle=0.0, threshold_speed=30.0, speed_duration_ms=100.0) is False
    assert eng._speed_threshold_active == 30.0

    # Update with high speed (>= 30.0) -> sets timer
    eng.update(0.030, 0.5, 0.0, 0.0)  # speed = 50.0 units/sec
    assert eng._speed_above_since == 0.030

    # Update with low speed (< 30.0) -> resets timer
    eng.update(0.040, 0.01, 0.0, 0.0)  # speed = 1.0 units/sec
    assert eng._speed_above_since == -1.0


def test_properties_and_buffering_return() -> None:
    """Verify cum_dz, turn_speed, pos_y properties and dt buffering early return."""
    eng = _make_engine()
    eng.update(0.0, 0.0, 0.0, 0.0)
    # Small dt (< 0.005s) should buffer and return early without computing speed
    eng.update(0.002, 1.0, 1.0, 1.0)
    assert eng.pos_x != 0.0
    assert eng.pos_y != 0.0
    assert eng.cum_dz != 0.0
    assert eng.turn_speed == 0.0  # not yet updated because buf_dt < 0.005s

    # Next update pushes buf_dt >= 0.005s
    eng.update(0.006, 1.0, 1.0, 1.0)
    assert eng.turn_speed != 0.0


def test_finite_helper_direct() -> None:
    """Direct test of KinematicEngine._finite static method."""
    assert KinematicEngine._finite(1.0) is True
    assert KinematicEngine._finite(0.0) is True
    assert KinematicEngine._finite(-42.5) is True
    assert KinematicEngine._finite(None) is False
    assert KinematicEngine._finite(float("nan")) is False
    assert KinematicEngine._finite(float("inf")) is False
    assert KinematicEngine._finite(float("-inf")) is False
    assert KinematicEngine._finite("invalid") is False  # type: ignore
    assert KinematicEngine._finite(object()) is False  # type: ignore




