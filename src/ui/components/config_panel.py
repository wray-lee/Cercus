"""Dynamic config panel — generates form from paradigm schema."""
from typing import Dict, Any
from nicegui import ui

from src.models.paradigm import PARADIGM_REGISTRY


def config_panel(on_paradigm_change=None) -> tuple:
    """Build the config panel. Returns (container, get_form_values callable)."""
    form_values: Dict[str, Any] = {}
    param_container = None

    with ui.card().classes('w-full glass-card') as card:
        # --- Fixed config fields (two-column grid for compactness) ---
        ui.label('Configuration').classes('text-sm font-bold mb-2').style('color: #F1F5F9;')

        with ui.row().classes('w-full items-center gap-1'):
            subject_input = ui.input('Subject ID', value='').props('dense outlined').classes('flex-grow')
            ui.button('New', on_click=lambda: _new_subject(subject_input)).props('dense size=sm').classes('text-[10px]')

        paradigm_names = list(PARADIGM_REGISTRY.keys())
        paradigm_select = ui.select(
            paradigm_names,
            value=paradigm_names[0] if paradigm_names else '',
            label='Paradigm',
        ).props('dense outlined').classes('w-full')

        pattern_select = ui.select([], label='Pattern').props('dense outlined').classes('w-full')

        # Two-column grid for compact layout
        with ui.element('div').classes('grid grid-cols-2 gap-1 w-full'):
            session_start = ui.number('Session Start', value=1, min=1, step=1).props('dense outlined')
            session_total = ui.number('Total Sessions', value=2, min=1, step=1).props('dense outlined')
            iti_input = ui.input('ITI (sec)', value='60-90').props('dense outlined')
            isi_input = ui.input('ISI (sec)', value='300-300').props('dense outlined')

        # Detect available serial ports
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
            port_options = ['mock'] + ports if ports else ['mock']
        except ImportError:
            port_options = ['mock']

        serial_input = ui.select(port_options, value='mock', label='Serial Port').props('dense outlined').classes('flex-grow')

        with ui.element('div').classes('grid grid-cols-2 gap-1 w-full'):
            screen_id = ui.number('Screen ID', value=1, min=0, step=1).props('dense outlined')
            resolution_input = ui.input('Resolution', value='3840, 1080').props('dense outlined')
            view_dist = ui.number('View Dist (cm)', value=30.0).props('dense outlined')
            screen_w = ui.number('Screen W (cm)', value=53.0).props('dense outlined')

        debug_switch = ui.switch('Debug Mode', value=False).props('dense')

        # --- Dynamic paradigm params ---
        ui.separator().classes('my-1')
        ui.label('Paradigm Parameters').classes('text-sm font-semibold mb-1').style('color: #94A3B8;')
        param_container = ui.column().classes('w-full gap-1')

    # Store references
    _refs = {
        'subject': subject_input, 'paradigm': paradigm_select,
        'pattern': pattern_select, 'session_start': session_start,
        'session_total': session_total, 'iti': iti_input, 'isi': isi_input,
        'serial': serial_input, 'screen_id': screen_id, 'resolution': resolution_input,
        'view_dist': view_dist, 'screen_w': screen_w, 'debug': debug_switch,
        'param_container': param_container, 'param_widgets': {},
    }

    def rebuild_params(p_name=None):
        p_name = p_name or paradigm_select.value
        p_cls = PARADIGM_REGISTRY.get(p_name)
        if not p_cls:
            return

        # Update patterns
        patterns = p_cls.get_available_patterns() if hasattr(p_cls, 'get_available_patterns') else []
        pattern_select.options = patterns
        if patterns and pattern_select.value not in patterns:
            pattern_select.value = patterns[0]
        pattern_select.update()

        # Rebuild param form
        param_container.clear()
        _refs['param_widgets'] = {}
        schema = p_cls.get_parameter_schema()
        with param_container:
            for key, meta in schema.items():
                p_type = meta.get('type', 'string')
                label = meta.get('label', key)
                default = meta.get('default', '')

                if p_type == 'info':
                    ui.label(label).classes('text-[10px] text-zinc-500 italic')
                elif p_type == 'choice':
                    w = ui.select(meta.get('choices', []), value=str(default), label=label).props('dense outlined').classes('w-full')
                    _refs['param_widgets'][key] = w
                elif p_type == 'bool':
                    w = ui.switch(label, value=bool(default)).props('dense')
                    _refs['param_widgets'][key] = w
                elif p_type == 'int':
                    w = ui.number(label, value=int(default) if default != '' else 0).props('dense outlined').classes('w-full')
                    _refs['param_widgets'][key] = w
                elif p_type == 'float':
                    w = ui.number(label, value=float(default) if default != '' else 0.0).props('dense outlined').classes('w-full')
                    _refs['param_widgets'][key] = w
                else:
                    w = ui.input(label, value=str(default)).props('dense outlined').classes('w-full')
                    _refs['param_widgets'][key] = w

        if on_paradigm_change:
            on_paradigm_change(p_name)

    paradigm_select.on_value_change(lambda e: rebuild_params(e.value))
    # Initial build
    rebuild_params()

    def get_form_values() -> dict:
        """Collect current form values into a dict for build_config."""
        paradigm_params = {}
        for key, widget in _refs['param_widgets'].items():
            paradigm_params[key] = widget.value

        return {
            'paradigm': paradigm_select.value,
            'pattern': pattern_select.value,
            'subject_id': subject_input.value,
            'session_start': str(int(session_start.value)) if session_start.value else '1',
            'session_total': str(int(session_total.value)) if session_total.value else '2',
            'iti_range': iti_input.value,
            'isi_range': isi_input.value,
            'serial_port': serial_input.value,
            'screen_id': str(int(screen_id.value)) if screen_id.value else '1',
            'debug': debug_switch.value,
            'viewing_distance_cm': str(view_dist.value),
            'screen_width_cm': str(screen_w.value),
            'resolution': resolution_input.value,
            'paradigm_params': paradigm_params,
        }

    return card, get_form_values


def _new_subject(input_widget):
    import time
    ts = time.strftime('%Y%m%d_%H%M%S')
    input_widget.value = f'cricket_{ts}'
