"""Twin stimulus preview — NiceGUI component wrapping HTML5 Canvas."""
import json
from pathlib import Path
from nicegui import ui

_JS_TEXT = (Path(__file__).parent / 'twin_preview.js').read_text(encoding='utf-8')


def twin_preview_canvas() -> ui.element:
    """Create a twin preview canvas element.

    The canvas uses CSS aspect-ratio:8/3 matching the v1.0.0 virtual
    coordinate system (400x150).  The JS renderer derives pixel height
    from clientWidth (sizeCanvas pattern from v1.0.0), so it works
    correctly regardless of the CSS height.
    """
    # Inject JS per-page (not global) — each NiceGUI page context needs its own script
    ui.add_body_html(f'<script>{_JS_TEXT}</script>')

    container = ui.element('div').classes('w-full').style(
        'background: #000; border-radius: 6px; overflow: hidden; '
        'aspect-ratio: 8/3; min-height: 60px;'
    )
    canvas_id = f'twin-{id(container)}'
    with container:
        ui.html(
            f'<canvas id="{canvas_id}" '
            f'style="width:100%;aspect-ratio:8/3;display:block;"></canvas>'
        )
    container._twin_canvas_id = canvas_id
    return container


async def update_twin(container, twin_data):
    """Push new twin data to the canvas."""
    data = {'canvasId': container._twin_canvas_id, 'twin': twin_data}
    await ui.run_javascript(f'window.cercusTwin && window.cercusTwin({json.dumps(data)})')
