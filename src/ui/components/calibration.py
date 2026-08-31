"""Calibration matrix display — load from json, show 3x3, apply button."""
import json
from nicegui import ui


def calibration_panel(controller) -> ui.element:
    """Compact calibration panel showing the 3x3 matrix (auto-loaded)."""
    with ui.card().classes('w-full') as panel:
        ui.label('Calibration').classes('text-xs font-semibold text-zinc-300 mb-1')
        matrix_grid = ui.element('div').classes(
            'grid grid-cols-3 gap-1 font-mono text-[10px] text-center'
        )
        status_label = ui.label('').classes('text-[9px] text-zinc-500 mt-0.5')

    def refresh():
        _render_matrix(matrix_grid, controller.calib_matrix)
        if controller.calib_matrix:
            status_label.text = '✓ Loaded'
            status_label.classes(replace='text-[9px] text-lime-400 mt-0.5')
        else:
            status_label.text = 'No matrix'
            status_label.classes(replace='text-[9px] text-zinc-500 mt-0.5')

    panel._calib_refresh = refresh
    # Initial load attempt
    controller.load_calibration_matrix()
    refresh()
    return panel


def calibration_display(controller) -> ui.element:
    """Read-only matrix display for /monitor."""
    with ui.card().classes('w-full') as card:
        ui.label('Calibration Matrix').classes('text-sm font-semibold text-zinc-300 mb-1')
        matrix_grid = ui.element('div').classes(
            'grid grid-cols-3 gap-1 font-mono text-xs text-center'
        )

    def refresh():
        _render_matrix(matrix_grid, controller.calib_matrix)

    card._calib_refresh = refresh
    return card


def _render_matrix(grid, matrix):
    grid.clear()
    if not matrix:
        with grid:
            for _ in range(9):
                ui.label('—').classes('bg-[#0E0E11] rounded px-1 py-0.5 text-[10px] text-zinc-500')
        return
    with grid:
        for row in matrix:
            for val in row:
                v = f'{val:.3f}' if isinstance(val, (int, float)) else str(val)
                ui.label(v).classes('bg-[#0E0E11] rounded px-1 py-0.5 text-[10px] text-zinc-200')
