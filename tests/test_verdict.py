"""Tests for post-trial behavioral verdict classification.

Seam: BaseParadigm.classify_response(engine, trial_context, trial_duration) → dict
"""
import pytest
from src.core.kinematics import KinematicEngine
from src.models.paradigm import BaseParadigm, LoomingParadigm


def _make_engine(**overrides) -> KinematicEngine:
    """Build a KinematicEngine with known accumulated values."""
    eng = KinematicEngine()
    eng.reset()
    # Directly set slots to simulate post-trial state
    for attr, val in overrides.items():
        setattr(eng, f"_{attr}", val)
    return eng


def test_zero_motion_yields_no_response():
    eng = _make_engine(cum_disp=0.0, cum_dz=0.0, move_speed=0.0)
    paradigm = LoomingParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"screen_side": "left"}, 8.0)
    assert result["response"] == "no_response"
    assert result["cum_disp"] == 0.0
    assert result["cum_dz"] == 0.0
    assert "peak_speed" in result


def test_high_displacement_yields_escape():
    eng = _make_engine(cum_disp=18.3, cum_dz=2.0, move_speed=45.0)
    paradigm = LoomingParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"screen_side": "left"}, 8.0)
    assert result["response"] == "escape"
    assert result["cum_disp"] == 18.3


def test_high_angle_yields_escape():
    eng = _make_engine(cum_disp=1.0, cum_dz=35.0, move_speed=10.0)
    paradigm = LoomingParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"screen_side": "right"}, 8.0)
    assert result["response"] == "escape"
    assert result["cum_dz"] == 35.0


def test_moderate_displacement_yields_startle():
    eng = _make_engine(cum_disp=8.0, cum_dz=3.0, move_speed=20.0)
    paradigm = LoomingParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"screen_side": "left"}, 8.0)
    assert result["response"] == "startle"


def test_moderate_angle_yields_startle():
    eng = _make_engine(cum_disp=2.0, cum_dz=15.0, move_speed=10.0)
    paradigm = LoomingParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"screen_side": "right"}, 8.0)
    assert result["response"] == "startle"


def test_negative_angle_uses_absolute_value():
    """cum_dz can be negative (turned left). Classification uses |cum_dz|."""
    eng = _make_engine(cum_disp=1.0, cum_dz=-35.0, move_speed=5.0)
    paradigm = LoomingParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"screen_side": "left"}, 8.0)
    assert result["response"] == "escape"
    assert result["cum_dz"] == 35.0  # absolute value in output


def test_base_paradigm_default_works_on_any_paradigm():
    """classify_response is inherited — non-looming paradigms get the default."""
    from src.models.paradigm import BlankParadigm
    eng = _make_engine(cum_disp=20.0, cum_dz=5.0, move_speed=30.0)
    paradigm = BlankParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"type": "blank_tracking"}, 10.0)
    assert result["response"] == "escape"
    assert set(result.keys()) == {"response", "cum_disp", "cum_dz", "peak_speed"}


def test_peak_move_speed_used_in_verdict():
    """classify_response uses engine.effective_speed (peak when > 0)."""
    eng = _make_engine(cum_disp=0.0, cum_dz=0.0, move_speed=0.0, peak_move_speed=120.0)
    paradigm = LoomingParadigm(debug_mode=True)
    result = paradigm.classify_response(eng, {"screen_side": "left"}, 8.0)
    assert result["peak_speed"] == 120.0

