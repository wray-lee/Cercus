"""Custom titlebar for frameless window."""
from nicegui import ui, app


def titlebar():
    """Build draggable titlebar with window controls."""
    with ui.row().classes('w-full h-9 items-center px-4 gap-2 drag-handle').style(
        'background: linear-gradient(135deg, #0A0A0B 0%, #141416 100%); '
        'border-bottom: 1px solid #262629; '
        'flex-shrink: 0; '
        'box-shadow: 0 1px 3px rgba(0,0,0,0.5);'
    ):
        ui.label('Cercus').classes('text-sm font-bold text-cyan-400')
        ui.label('·').classes('text-zinc-700')
        ui.label('Experiment Dashboard').classes('text-xs text-zinc-500')

        ui.element('div').classes('flex-grow')  # spacer

        # Window controls with hover effects
        with ui.row().classes('gap-1 items-center'):
            ui.button(icon='remove', on_click=_minimize).props('flat dense round size=sm').classes(
                'text-zinc-400 hover:bg-zinc-800 transition-colors'
            ).style('width: 28px; height: 28px;')
            ui.button(icon='crop_square', on_click=_maximize).props('flat dense round size=sm').classes(
                'text-zinc-400 hover:bg-zinc-800 transition-colors'
            ).style('width: 28px; height: 28px;')
            ui.button(icon='close', on_click=_close).props('flat dense round size=sm').classes(
                'text-zinc-400 hover:bg-red-900 transition-colors'
            ).style('width: 28px; height: 28px;')


def _minimize():
    """Minimize window."""
    if app.native.main_window:
        app.native.main_window.minimize()


def _maximize():
    """Toggle maximize window."""
    if app.native.main_window:
        app.native.main_window.toggle_fullscreen()


def _close():
    """Close window."""
    if app.native.main_window:
        app.native.main_window.destroy()
