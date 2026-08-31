"""Trajectory canvas — NiceGUI component wrapping HTML5 Canvas."""
import json
from pathlib import Path
from nicegui import ui

_JS_TEXT = (Path(__file__).parent / 'trajectory.js').read_text(encoding='utf-8')
_JS_INJECTED = set()  # track per-client injection


def trajectory_canvas(state) -> ui.element:
    """Create a trajectory canvas element bound to AppState."""
    container = ui.element('div').classes('w-full aspect-square bg-black rounded-lg overflow-hidden')
    canvas_id = f'traj-{id(container)}'

    # Inject JS once per page render (inside page function, not global scope)
    ui.add_body_html(f'<script>{_JS_TEXT}</script>')

    with container:
        ui.html(f'<canvas id="{canvas_id}" style="width:100%;height:100%"></canvas>')

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
