"""Tests for KinematicsParser — calibration, single-pass parsing, zero-allocation.

Seam: KinematicsParser.parse / get_telemetry / _apply_calibration
"""
import pytest

from src.core.hardware import KinematicsParser


def _make_parser():
    return KinematicsParser()


def test_parse_returns_calibrated_row():
    p = _make_parser()
    row = p.parse(1.0, "100,5,3,2,1", 1)
    assert row is not None
    # row: [sys_time_str, ard_time, dx, dy, dz, stim_state, g_id]
    assert len(row) == 7
    assert row[-1] == 1  # global_trial_id


def test_parse_empty_returns_none():
    p = _make_parser()
    assert p.parse(1.0, "", 1) is None
    assert p.parse(1.0, "  ", 1) is None


def test_single_pass_no_double_accumulation():
    """B1/B2: Calling parse() once must not double-accumulate.
    With jitter_thresh=0, accum should reset after each emit.
    Parse two samples and verify dx values are independent."""
    p = _make_parser()
    row1 = p.parse(1.0, "100,10,0,0,0", 1)
    row2 = p.parse(2.0, "200,10,0,0,0", 2)
    # With identity matrix and thresh=0, each sample should produce dx=10
    assert row1 is not None
    assert row2 is not None
    # dx is at index 1 (after sys_time at 0)
    assert float(row1[1+1]) == 10.0  # field index 1 = dx
    assert float(row2[1+1]) == 10.0  # not 20 (which would mean double-accumulation)


def test_get_telemetry_returns_dict():
    p = _make_parser()
    tel = p.get_telemetry("100,5,3,2,1")
    assert isinstance(tel, dict)
    assert "dx" in tel
    assert "dy" in tel
    assert "dz" in tel


def test_parse_and_get_telemetry_both_mutate_accumulator():
    """Verify that calling parse() then get_telemetry() on the same data
    double-counts — this is the bug we fixed by NOT doing both."""
    p = _make_parser()
    # First: parse (accumulates dx=10 then emits)
    p.parse(1.0, "100,10,0,0,0", 1)
    # Second: get_telemetry on same data (would accumulate again!)
    tel = p.get_telemetry("100,10,0,0,0")
    # With thresh=0 and identity matrix, this second call also emits 10
    # But the accumulator was already drained by parse(), so this is
    # a fresh accumulation — the issue was that BOTH were called in
    # _drain_hardware, meaning kinematic engine got 2x the displacement.
    assert float(tel["dx"]) == 10.0


def test_idx_map_precomputed():
    """M3: idx_map should be precomputed in __init__, not per-call."""
    p = _make_parser()
    assert hasattr(p, '_idx_map')
    assert 'dx' in p._idx_map
    assert 'dy' in p._idx_map
    assert 'dz' in p._idx_map


def test_out_buf_precomputed():
    """M3: _out_buf should exist for zero-allocation reuse."""
    p = _make_parser()
    assert hasattr(p, '_out_buf')
    assert len(p._out_buf) == len(p._field_defs)


def test_field_keys_property():
    """field_keys should be a public tuple matching _field_defs keys."""
    p = _make_parser()
    assert isinstance(p.field_keys, tuple)
    assert p.field_keys == ('ard_time', 'dx', 'dy', 'dz', 'stim_state')


def test_calibration_matrix_applied():
    """Verify calibration matrix transforms displacements."""
    p = _make_parser()
    # Swap dx and dy via matrix
    p.set_calib_matrix([[0, 1, 0], [1, 0, 0], [0, 0, 1]])
    tel = p.get_telemetry("100,10,20,0,0")
    assert float(tel["dx"]) == 20.0  # was dy
    assert float(tel["dy"]) == 10.0  # was dx
