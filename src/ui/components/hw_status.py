"""Hardware state display — NiceGUI component."""
from nicegui import ui

# Axis colors matching v1.0.0 odometer style
_ODO_COLORS = {
    'dx': 'var(--accent)',   # mint (was cyan)
    'dy': 'var(--ok)',       # olive (was lime)
    'dz': 'var(--warn)',     # warm orange
}

_ODO_KEYS = ('dx', 'dy', 'dz')


def hw_status_panel(state) -> ui.element:
    """Create hardware metrics display bound to AppState."""
    with ui.card().classes('w-full') as card:
        with ui.row().classes('items-center gap-1.5 mb-1'):
            ui.icon('memory').classes('text-[14px]').style('color: var(--text-muted);')
            ui.label('Hardware').classes('sec-title')

        # Prominent odometer row for DX, DY, DZ (v1.0.0 style)
        # Built once — refresh() updates text, not DOM structure.
        odo_labels = {}
        with ui.element('div').classes('grid grid-cols-3 gap-1 mb-1'):
            for key in _ODO_KEYS:
                color = _ODO_COLORS.get(key, 'var(--text)')
                with ui.element('div').classes('cell p-1.5 text-center'):
                    ui.label(key.upper()).classes('text-[9px] uppercase').style(
                        'color: var(--text-muted); letter-spacing: 0.05em;'
                    )
                    lbl = ui.label('—').classes('mono text-[18px] font-bold').style(
                        f'color: {color};'
                    )
                    odo_labels[key] = lbl

        # Generic metrics grid for everything else
        grid = ui.element('div').classes('grid grid-cols-3 gap-1')

    # Track previous values for change detection
    _prev = {}
    _prev_metrics_keys = {'_keys': None}

    def refresh():
        metrics = state.hardware_metrics or {}

        # ── Odometers: update text in place ──
        for key in _ODO_KEYS:
            val = metrics.get(key)
            v = f'{float(val):.2f}' if val is not None and _is_number(val) else '—'
            if _prev.get(key) != v:
                _prev[key] = v
                odo_labels[key].text = v

        # ── Other metrics — only rebuild grid when key set changes ──
        other_keys = tuple(
            k for k in metrics
            if not k.startswith('pos_') and not k.startswith('k_') and k not in _ODO_KEYS
        )
        if _prev_metrics_keys['_keys'] != other_keys:
            _prev_metrics_keys['_keys'] = other_keys
            # Key set changed — full rebuild
            grid.clear()
            if not other_keys:
                with grid:
                    ui.label('—').classes('text-[10px]').style('color: var(--text-muted);')
            else:
                _prev['_grid_labels'] = {}
                with grid:
                    for key in other_keys:
                        val = metrics.get(key)
                        v = val if val is not None else '—'
                        if isinstance(v, float):
                            v = f'{v:.2f}'
                        v_str = str(v)
                        _prev[key] = v_str
                        with ui.element('div').classes('cell p-1'):
                            ui.label(str(key).upper()).classes('text-[9px]').style(
                                'color: var(--text-muted);'
                            )
                            lbl = ui.label(v_str).classes('text-[10px] mono').style(
                                'color: var(--text);'
                            )
                            _prev['_grid_labels'][key] = lbl
        else:
            # Same keys — update values in place
            labels = _prev.get('_grid_labels', {})
            for key in other_keys:
                val = metrics.get(key)
                v = val if val is not None else '—'
                if isinstance(v, float):
                    v = f'{v:.2f}'
                v_str = str(v)
                if _prev.get(key) != v_str:
                    _prev[key] = v_str
                    lbl = labels.get(key)
                    if lbl:
                        lbl.text = v_str

    card._hw_refresh = refresh
    return card


def _is_number(v):
    try:
        float(v)
        return True
    except (ValueError, TypeError):
        return False
