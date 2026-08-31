"""Custom titlebar for frameless window."""
from nicegui import ui, app


def titlebar():
    """Build draggable titlebar with window controls."""
    with ui.row().classes('w-full items-center px-4 gap-2 drag-handle').style(
        'height: 28px; '
        'background: var(--surface); '
        'border-bottom: 1px solid var(--border); '
        'flex-shrink: 0;'
    ):
        ui.label('Cercus').classes('text-[13px] font-bold').style('color: var(--accent);')
        ui.label('·').style('color: var(--border);')
        ui.label('Experiment Dashboard').classes('text-[11px]').style('color: var(--text-muted);')

        ui.element('div').classes('flex-grow')  # spacer

        with ui.row().classes('gap-0.5 items-center'):
            _ctrl_btn('remove', _minimize)
            _ctrl_btn('crop_square', _maximize)
            _ctrl_btn('close', _close, hover_bg='rgba(199, 84, 73, 0.25)')


def _ctrl_btn(icon, handler, hover_bg='rgba(255,255,255,0.06)'):
    """Window control button — minimal, 24×24."""
    btn = ui.button(icon=icon, on_click=handler).props('flat dense round size=xs')
    btn.style(
        f'width: 24px; height: 24px; color: var(--text-muted); '
        f'--q-btn-hover-bg: {hover_bg};'
    )
    return btn


def _minimize():
    if app.native.main_window:
        app.native.main_window.minimize()


def _maximize():
    if app.native.main_window:
        app.native.main_window.toggle_fullscreen()


def _close():
    if app.native.main_window:
        app.native.main_window.destroy()
