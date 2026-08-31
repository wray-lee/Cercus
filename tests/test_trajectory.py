"""Tests for trajectory bbox and NaN guard in _update_trajectory.

Seam: MasterDashboard trajectory state management — None sentinel bbox,
monotonic expansion, NaN/inf filtering.
"""
import math
import pytest


class _FakeBbox:
    """Minimal stand-in for the bbox portion of MasterDashboard."""

    TRAIL_JUMP_MM = 50.0

    def __init__(self):
        self._trail_points = []
        self._trail_min_x = None
        self._trail_max_x = None
        self._trail_min_y = None
        self._trail_max_y = None

    def reset(self):
        self._trail_points = []
        self._trail_min_x = None
        self._trail_max_x = None
        self._trail_min_y = None
        self._trail_max_y = None

    def add_point(self, fpx: float, fpy: float) -> bool:
        """Mirrors the bbox logic from _update_trajectory.
        Returns False if the point was rejected (NaN/inf/jump)."""
        if not (math.isfinite(fpx) and math.isfinite(fpy)):
            return False
        if self._trail_points:
            lx, ly = self._trail_points[-1]
            if math.hypot(fpx - lx, fpy - ly) > self.TRAIL_JUMP_MM:
                self.reset()
                return False
        self._trail_points.append((fpx, fpy))
        self._trail_points = self._trail_points[-1000:]
        if self._trail_min_x is None:
            self._trail_min_x = self._trail_max_x = fpx
            self._trail_min_y = self._trail_max_y = fpy
        else:
            self._trail_min_x = min(self._trail_min_x, fpx)
            self._trail_max_x = max(self._trail_max_x, fpx)
            self._trail_min_y = min(self._trail_min_y, fpy)
            self._trail_max_y = max(self._trail_max_y, fpy)
        return True


def test_none_sentinel_seeded_from_first_point():
    b = _FakeBbox()
    assert b._trail_min_x is None
    b.add_point(10.0, 20.0)
    assert b._trail_min_x == 10.0
    assert b._trail_max_x == 10.0
    assert b._trail_min_y == 20.0
    assert b._trail_max_y == 20.0


def test_bbox_only_expands():
    b = _FakeBbox()
    b.add_point(0.0, 0.0)
    b.add_point(10.0, 10.0)
    assert b._trail_max_x == 10.0
    # New point inside existing bbox — bbox must NOT shrink
    b.add_point(5.0, 5.0)
    assert b._trail_min_x == 0.0
    assert b._trail_max_x == 10.0
    assert b._trail_min_y == 0.0
    assert b._trail_max_y == 10.0


def test_bbox_not_poisoned_by_origin_after_reset():
    """After reset at arbitrary position, bbox should not contain (0,0)."""
    b = _FakeBbox()
    b.add_point(40.0, 40.0)
    b.reset()
    b.add_point(41.0, 41.0)
    b.add_point(42.0, 42.0)
    assert b._trail_min_x == 41.0  # not 0.0
    assert b._trail_min_y == 41.0


def test_nan_rejected():
    b = _FakeBbox()
    assert b.add_point(float('nan'), 1.0) is False
    assert b._trail_min_x is None  # no state change
    assert len(b._trail_points) == 0


def test_inf_rejected():
    b = _FakeBbox()
    b.add_point(1.0, 1.0)
    assert b.add_point(float('inf'), 2.0) is False
    assert b._trail_max_x == 1.0  # unchanged


def test_jump_gate_resets_bbox():
    b = _FakeBbox()
    b.add_point(0.0, 0.0)
    b.add_point(1.0, 1.0)
    # Jump > 50mm
    assert b.add_point(100.0, 100.0) is False
    assert b._trail_min_x is None  # reset
    assert len(b._trail_points) == 0
