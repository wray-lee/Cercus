"""Dynamic config panel — generates form from paradigm schema.

Every widget here is produced from ``BaseParadigm.get_full_schema()``. This
module contains no paradigm names and no parameter names: visibility, enable
flags and grouping are all declared in the schema layer, so a new paradigm
never requires an edit to this file.
"""
import logging
from typing import Dict, Any
from nicegui import ui

from src.models.paradigm import PARADIGM_REGISTRY, schema_condition_met

log = logging.getLogger(__name__)


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

    def _snapshot():
        """Capture current widget values so a rebuild can restore them."""
        _refs['param_values'] = {
            k: w.value for k, w in _refs['param_widgets'].items()
        }

    def _make_widget(key, meta, value):
        """Build one widget from a schema entry, seeded with ``value``.

        Returns None for non-input entries (``info``). Bounds declared in the
        schema are passed through, which also re-activates NiceGUI's own
        blur-time clamp on ui.number.
        """
        p_type = meta.get('type', 'info')
        label = meta.get('label', key)
        lo, hi = meta.get('min'), meta.get('max')

        if p_type == 'info':
            ui.label(label).classes('text-[10px] text-zinc-500 italic')
            return None
        if p_type == 'choice':
            return ui.select(
                meta.get('choices', []), value=str(value), label=label,
            ).props('dense outlined').classes('w-full')
        if p_type == 'bool':
            return ui.switch(label, value=bool(value)).props('dense')
        if p_type in ('int', 'float'):
            cast = int if p_type == 'int' else float
            try:
                num = cast(value)
            except (TypeError, ValueError):
                num = cast(meta.get('default', 0))
            return ui.number(
                label, value=num, min=lo, max=hi,
            ).props('dense outlined').classes('w-full')
        if p_type == 'filepath':
            with ui.row().classes('w-full items-center gap-1'):
                w = ui.input(label, value=str(value)).props('dense outlined').classes('flex-grow')
                ui.button(
                    icon='folder_open', on_click=lambda: _pick_file(w),
                ).props('dense flat size=sm').tooltip('Browse')
            return w
        if p_type != 'string':
            log.warning(
                "config_panel: schema key %r declares unrecognised type %r; "
                "rendering as text input", key, p_type,
            )
        return ui.input(label, value=str(value)).props('dense outlined').classes('w-full')

    def rebuild_params(p_name=None, _defer=False):
        p_name = p_name or paradigm_select.value
        p_cls = PARADIGM_REGISTRY.get(p_name)
        if not p_cls:
            return

        # Deleting the element that fired the event, from inside its own
        # handler, leaves NiceGUI updating a dead widget. Reschedule instead.
        if _defer:
            ui.timer(0, lambda: rebuild_params(p_name), once=True)
            return

        # Update patterns
        patterns = p_cls.get_available_patterns() if hasattr(p_cls, 'get_available_patterns') else []
        pattern_select.options = patterns
        if patterns and pattern_select.value not in patterns:
            pattern_select.value = patterns[0]
        pattern_select.update()

        schema = p_cls.get_full_schema()

        # Carry operator edits across a rebuild; discard on paradigm change.
        same_paradigm = _refs.get('param_paradigm') == p_name
        saved = dict(_refs.get('param_values') or {}) if same_paradigm else {}

        # Resolve effective values BEFORE rendering, so a visibility gate sees
        # the operator's choice rather than a freshly-defaulted widget.
        vals, enabled = {}, {}
        for key, meta in schema.items():
            if meta.get('type') == 'info':
                continue
            vals[key] = saved.get(key, meta.get('default', ''))
            en_key = meta.get('enable_key')
            if en_key:
                enabled[en_key] = saved.get(
                    en_key, meta.get('enable_default', True)
                )

        param_container.clear()
        _refs['param_widgets'] = {}
        _refs['param_paradigm'] = p_name
        gate_params = set()

        with param_container:
            for key, meta in schema.items():
                cond = meta.get('visible_when')
                if cond:
                    gate_params.add(cond['param'])
                    if not schema_condition_met(vals.get(cond['param']), cond['equals']):
                        continue  # hidden: not rendered, not collected

                en_key = meta.get('enable_key')
                if en_key:
                    # Value + its enable flag share a row.
                    with ui.row().classes('w-full items-center gap-1 no-wrap'):
                        w = _make_widget(key, meta, vals.get(key))
                        if w is not None:
                            w.classes('flex-grow')
                        if en_key not in _refs['param_widgets']:
                            label = meta.get('label', key)
                            cb = ui.checkbox(
                                '', value=bool(enabled[en_key]),
                            ).props(f'dense aria-label="Enable {label}"')
                            _refs['param_widgets'][en_key] = cb
                else:
                    w = _make_widget(key, meta, vals.get(key))

                if w is not None:
                    _refs['param_widgets'][key] = w

        # Rebuild when any gating param changes — no literal key anywhere.
        for dep in gate_params:
            dep_widget = _refs['param_widgets'].get(dep)
            if dep_widget:
                dep_widget.on_value_change(
                    lambda e, n=p_name: (_snapshot(), rebuild_params(n, _defer=True))
                )

        if on_paradigm_change:
            on_paradigm_change(p_name)

    def _pick_file(input_widget):
        """Populate a filepath input from a native picker when available."""
        try:
            from nicegui import app
            window = getattr(app.native, 'main_window', None)
            if window is not None:
                paths = window.create_file_dialog()
                if paths:
                    input_widget.value = paths[0]
                return
        except Exception:  # pragma: no cover - picker is best-effort
            log.debug('config_panel: native file dialog unavailable', exc_info=True)
        ui.notify('Type the file path directly (no picker available)', type='info')

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
