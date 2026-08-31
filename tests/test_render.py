"""Tests for CoreRenderer statelessness and command-drawing dispatch."""
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_psychopy(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Mock PsychoPy module and visual objects."""
    import sys
    import types

    psychopy_mod = types.ModuleType("psychopy")
    visual_mod = types.ModuleType("psychopy.visual")

    mock_win = MagicMock()
    mock_circle = MagicMock()
    mock_rect = MagicMock()
    mock_stim = MagicMock()

    visual_mod.Window = MagicMock(return_value=mock_win)
    visual_mod.Circle = MagicMock(return_value=mock_circle)
    visual_mod.Rect = MagicMock(return_value=mock_rect)
    visual_mod.ShapeStim = MagicMock(return_value=mock_stim)
    visual_mod.ElementArrayStim = MagicMock(return_value=mock_stim)

    psychopy_mod.visual = visual_mod
    monkeypatch.setitem(sys.modules, "psychopy", psychopy_mod)
    monkeypatch.setitem(sys.modules, "psychopy.visual", visual_mod)

    return visual_mod


def test_core_renderer_attributes(mock_psychopy: Any) -> None:
    """Verify CoreRenderer only maintains allowed window/stimulus handles without trial state."""
    from src.core.render import CoreRenderer

    renderer = CoreRenderer(
        win_size=(800, 600),
        is_fullscr=False,
        screen_id=0,
        wait_blanking=False,
    )

    allowed = {"win", "objects", "visual"}
    instance_attrs = set(vars(renderer).keys())
    assert instance_attrs.issubset(allowed), f"Unexpected attributes in renderer: {instance_attrs - allowed}"

    # Verify no timing, frame count, trial index, or paradigm logic in instance variables
    forbidden_terms = ["trial", "frame", "time", "clock", "state", "phase", "verdict", "metric"]
    for attr in instance_attrs:
        for term in forbidden_terms:
            assert term not in attr.lower(), f"Stateful attribute name detected: {attr}"


def test_core_renderer_stateless_command_dispatch(mock_psychopy: Any) -> None:
    """Verify drawing commands do not create state machine tracking."""
    from src.core.render import CoreRenderer

    renderer = CoreRenderer(
        win_size=(800, 600),
        is_fullscr=False,
        screen_id=0,
        wait_blanking=False,
    )

    cmds: List[Dict[str, Any]] = [
        {"id": "c1", "type": "circle", "radius": 50, "pos": (0, 0), "fillColor": [1, 1, 1]},
        {"id": "r1", "type": "rect", "width": 100, "height": 50, "pos": (10, 10)},
    ]

    renderer.draw_commands(cmds)
    assert "c1" in renderer.objects
    assert "r1" in renderer.objects

    renderer.flip()
    renderer.win.flip.assert_called_once()


def test_core_renderer_render_frame_and_close(mock_psychopy: Any) -> None:
    """Verify render_frame composite and close calls."""
    from src.core.render import CoreRenderer

    renderer = CoreRenderer(
        win_size=(800, 600),
        is_fullscr=False,
        screen_id=0,
        wait_blanking=False,
    )

    cmds: List[Dict[str, Any]] = [
        {"id": "c1", "type": "circle", "radius": 20, "pos": (0, 0)},
    ]
    renderer.render_frame(cmds)
    assert renderer.win.flip.call_count == 1

    renderer.close()
    assert renderer.win.close.call_count == 1
