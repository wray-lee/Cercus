"""Hardware state display — NiceGUI component."""
from nicegui import ui


def hw_status_panel(state) -> ui.element:
    """Create hardware metrics display bound to AppState."""
    with ui.card().classes('w-full') as card:
        ui.label('Hardware State').classes('text-sm font-semibold text-zinc-300 mb-1')
        grid = ui.element('div').classes('grid grid-cols-3 gap-2')

    def refresh():
        grid.clear()
        metrics = state.hardware_metrics
        if not metrics:
            with grid:
                ui.label('—').classes('text-xs text-zinc-500')
            return
        with grid:
            for key, val in metrics.items():
                if key.startswith('pos_') or key.startswith('k_'):
                    continue  # shown in trajectory panel
                with ui.element('div').classes('bg-[#0E0E11] border border-[#1f1f22] rounded-lg p-1.5'):
                    ui.label(str(key).upper()).classes('text-[10px] text-zinc-500')
                    v = val if val is not None else '—'
                    if isinstance(v, float):
                        v = f'{v:.2f}'
                    ui.label(str(v)).classes('text-xs text-zinc-200 mono')

    card._hw_refresh = refresh
    return card
