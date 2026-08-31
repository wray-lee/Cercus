"""Calibration matrix display — load from json, show 3x3, apply button."""
import json
from nicegui import ui


def calibration_panel(controller) -> ui.element:
    """Collapsible calibration panel showing the 3x3 matrix."""
    with ui.expansion('Calibration Matrix', icon='grid_on').classes('w-full') as panel:
        matrix_grid = ui.element('div').classes(
            'grid grid-cols-3 gap-1 font-mono text-xs text-center'
        )
        status_label = ui.label('No matrix loaded').classes('text-xs text-zinc-500 mt-1')

        with ui.row().classes('gap-2 mt-2'):
            ui.button('Load from file', on_click=lambda: _load(controller, matrix_grid, status_label)).classes('text-xs')
            ui.button('Apply', on_click=lambda: _apply(controller, status_label)).classes('text-xs')

    def refresh():
        _render_matrix(matrix_grid, controller.calib_matrix)
        if controller.calib_matrix:
            status_label.text = 'Matrix loaded'
            status_label.classes(replace='text-xs text-lime-400 mt-1')
        else:
            status_label.text = 'No matrix loaded'
            status_label.classes(replace='text-xs text-zinc-500 mt-1')

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
                ui.label('—').classes('bg-[#0E0E11] rounded px-2 py-1 text-zinc-500')
        return
    with grid:
        for row in matrix:
            for val in row:
                v = f'{val:.4f}' if isinstance(val, (int, float)) else str(val)
                ui.label(v).classes('bg-[#0E0E11] rounded px-2 py-1 text-zinc-200')


def _load(controller, grid, status):
    result = controller.load_calibration_matrix()
    if result:
        _render_matrix(grid, result)
        status.text = 'Matrix loaded'
        status.classes(replace='text-xs text-lime-400 mt-1')
    else:
        status.text = 'Failed to load calibration_cfg.json'
        status.classes(replace='text-xs text-red-400 mt-1')


def _apply(controller, status):
    if controller.calib_matrix:
        status.text = 'Matrix applied (will inject into next experiment)'
        status.classes(replace='text-xs text-cyan-400 mt-1')
    else:
        status.text = 'No matrix to apply'
        status.classes(replace='text-xs text-red-400 mt-1')
