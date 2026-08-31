"""Trajectory canvas — NiceGUI Vue component wrapping HTML5 Canvas."""
from pathlib import Path
from nicegui import ui

JS_FILE = Path(__file__).parent / 'trajectory.js'


def trajectory_canvas(state) -> ui.element:
    """Create a trajectory canvas element bound to AppState."""
    canvas = ui.html('').classes('w-full')
    canvas_id = f'traj-{id(canvas)}'

    ui.add_body_html(f'''
    <script>
    {JS_FILE.read_text(encoding="utf-8")}
    </script>
    ''')

    container = ui.element('div').classes('w-full aspect-square bg-black rounded-lg overflow-hidden')
    with container:
        ui.html(f'<canvas id="{canvas_id}" style="width:100%;height:100%"></canvas>')

    async def update():
        data = {
            'canvasId': canvas_id,
            'trail_points': state.trail_points[-1000:],
            'min_x': state._trail_min_x,
            'max_x': state._trail_max_x,
            'min_y': state._trail_min_y,
            'max_y': state._trail_max_y,
            'angle': state.trail_angle,
        }
        await ui.run_javascript(f'window.cercusTraj && window.cercusTraj({__import__("json").dumps(data)})')

    container._traj_update = update
    return container
