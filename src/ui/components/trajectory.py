"""Trajectory canvas — NiceGUI component wrapping HTML5 Canvas."""
import json
from pathlib import Path
from nicegui import ui

_JS_TEXT = (Path(__file__).parent / 'trajectory.js').read_text(encoding='utf-8')


def trajectory_canvas(state) -> ui.element:
    """Create a trajectory canvas element bound to AppState.

    The canvas uses CSS aspect-ratio:1 matching the v1.0.0 virtual
    coordinate system (150x150).  The JS renderer derives pixel height
    from clientWidth (sizeCanvas pattern from v1.0.0), so it works
    correctly regardless of the CSS height.
    """
    container = ui.element('div').classes('w-full overflow-hidden').style(
        'background: #000; border-radius: 6px; aspect-ratio: 1; min-height: 80px;'
    )
    canvas_id = f'traj-{id(container)}'

    # Inject JS once per page render
    ui.add_body_html(f'<script>{_JS_TEXT}</script>')

    with container:
        ui.html(
            f'<canvas id="{canvas_id}" '
            f'style="width:100%;aspect-ratio:1;display:block;"></canvas>'
        )

    async def update():
        bbox = state.trail_bbox
        data = {
            'canvasId': canvas_id,
            'trail_points': state.trail_points[-1000:],
            'min_x': bbox[0] if bbox else None,
            'max_x': bbox[1] if bbox else None,
            'min_y': bbox[2] if bbox else None,
            'max_y': bbox[3] if bbox else None,
            'angle': state.trail_angle,
        }
        await ui.run_javascript(f'window.cercusTraj && window.cercusTraj({json.dumps(data)})')

    container._traj_update = update
    return container
