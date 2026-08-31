"""Calibration matrix display — load from json, show 3x3."""
from nicegui import ui


def calibration_panel(controller) -> ui.element:
    """Compact calibration panel showing the 3x3 matrix (auto-loaded)."""
    with ui.card().classes('w-full') as panel:
        with ui.row().classes('items-center gap-2 mb-1'):
            ui.icon('grid_on').classes('text-[14px]').style('color: var(--text-muted);')
            ui.label('Calibration').classes('sec-title')
            # Dynamic status badge (v1.0.0 calPill equivalent)
            status_badge = ui.label('IDLE').classes(
                'mono text-[9px] font-bold px-1.5 py-0.5 rounded-full'
            ).style('background: var(--border); color: var(--text-muted);')
        matrix_grid = ui.element('div').classes(
            'grid grid-cols-3 gap-1 font-mono text-[10px] text-center'
        )
        # Status log line (v1.0.0 calStatus equivalent)
        status_line = ui.label('').classes('text-[9px] mono mt-0.5 truncate').style(
            'color: var(--text-muted);'
        )

    def refresh():
        _render_matrix(matrix_grid, controller.calib_matrix)
        if controller.calib_matrix:
            status_badge.text = 'LOADED'
            status_badge.style('background: var(--accent); color: var(--bg);')
            status_line.text = '✓ Matrix loaded from calibration_cfg.json'
            status_line.style('color: var(--ok);')
        else:
            status_badge.text = 'NONE'
            status_badge.style('background: var(--border); color: var(--text-muted);')
            status_line.text = 'No calibration matrix available'
            status_line.style('color: var(--text-muted);')

    panel._calib_refresh = refresh
    # Initial load attempt
    controller.load_calibration_matrix()
    refresh()
    return panel


def calibration_display(controller) -> ui.element:
    """Read-only matrix display for /monitor."""
    with ui.card().classes('w-full') as card:
        with ui.row().classes('items-center gap-2 mb-1'):
            ui.icon('grid_on').classes('text-[14px]').style('color: var(--text-muted);')
            ui.label('Calibration Matrix').classes('sec-title')
            status_badge = ui.label('').classes(
                'mono text-[9px] font-bold px-1.5 py-0.5 rounded-full'
            )
        matrix_grid = ui.element('div').classes(
            'grid grid-cols-3 gap-1 font-mono text-xs text-center'
        )

    def refresh():
        _render_matrix(matrix_grid, controller.calib_matrix)
        if controller.calib_matrix:
            status_badge.text = 'LOADED'
            status_badge.style('background: var(--accent); color: var(--bg);')
        else:
            status_badge.text = 'NONE'
            status_badge.style('background: var(--border); color: var(--text-muted);')

    card._calib_refresh = refresh
    # Auto-load on initial render (match dashboard behavior)
    controller.load_calibration_matrix()
    refresh()
    return card


def _render_matrix(grid, matrix):
    grid.clear()
    if not matrix:
        with grid:
            for _ in range(9):
                ui.label('—').classes('cell rounded px-1 py-0.5 text-[10px]').style(
                    'color: var(--text-muted);'
                )
        return
    with grid:
        for row in matrix:
            for val in row:
                v = f'{val:.3f}' if isinstance(val, (int, float)) else str(val)
                ui.label(v).classes('cell rounded px-1 py-0.5 text-[10px]').style(
                    'color: var(--text);'
                )
