"""Custom titlebar for frameless window."""
from nicegui import ui, app


def titlebar():
    """Build draggable titlebar with window controls."""
    with ui.row().classes('w-full h-9 items-center px-4 gap-2 drag-handle').style(
        'background: linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.95) 100%); '
        'border-bottom: 1px solid rgba(59, 130, 246, 0.3); '
        'flex-shrink: 0; '
        'box-shadow: 0 2px 8px rgba(0,0,0,0.5);'
    ):
        ui.label('Cercus').classes('text-sm font-bold').style('color: #60A5FA;')
        ui.label('·').classes('text-zinc-600')
        ui.label('Experiment Dashboard').classes('text-xs').style('color: #94A3B8;')

        ui.element('div').classes('flex-grow')  # spacer

        # Window controls with hover effects
        with ui.row().classes('gap-1 items-center'):
            ui.button(icon='remove', on_click=_minimize).props('flat dense round size=sm').classes(
                'text-zinc-400 hover:bg-blue-900 transition-colors'
            ).style('width: 28px; height: 28px;')
            ui.button(icon='crop_square', on_click=_maximize).props('flat dense round size=sm').classes(
                'text-zinc-400 hover:bg-blue-900 transition-colors'
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
