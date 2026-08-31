"""Twin stimulus preview — NiceGUI component wrapping HTML5 Canvas."""
import json
from pathlib import Path
from nicegui import ui

JS_FILE = Path(__file__).parent / 'twin_preview.js'
_JS_INJECTED = False


def twin_preview_canvas() -> ui.element:
    """Create a twin preview canvas element."""
    global _JS_INJECTED
    if not _JS_INJECTED:
        ui.add_body_html(f'<script>{JS_FILE.read_text(encoding="utf-8")}</script>')
        _JS_INJECTED = True

    canvas_id = f'twin-{id(object())}'
    container = ui.element('div').classes('w-full bg-black rounded-lg overflow-hidden')
    container.style('aspect-ratio: 400/150')
    with container:
        ui.html(f'<canvas id="{canvas_id}" style="width:100%;height:100%"></canvas>')
    container._twin_canvas_id = canvas_id
    return container


async def update_twin(container, twin_data):
    """Push new twin data to the canvas."""
    data = {'canvasId': container._twin_canvas_id, 'twin': twin_data}
    await ui.run_javascript(f'window.cercusTwin && window.cercusTwin({json.dumps(data)})')
