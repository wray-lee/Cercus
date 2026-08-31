"""NiceGUI application entry point.

Run with: python main.py
"""
import multiprocessing as mp
import secrets

from src.ui.controller import ExperimentController
from src.ui.state import AppState

# ── Shared state (single process, all clients see the same) ──
controller = ExperimentController()
state = AppState()

# ── Dashboard access token ──
DASHBOARD_TOKEN = secrets.token_urlsafe(32)


def _global_poll():
    """Single global polling loop — drains mp.Queue once, updates shared state."""
    events = controller.poll_telemetry()
    state.apply(events)
    if state.worker_died:
        terminal = events.get('terminal')
        if terminal:
            controller.terminal_status = terminal.get('action', '')
            controller.terminal_error = terminal.get('error', '')
        elif not controller.terminal_status:
            # Worker died without sending a terminal event
            controller.terminal_status = 'worker_error'
            controller.terminal_error = 'Worker process exited unexpectedly'
        controller.cleanup_worker()


def main():
    mp.set_start_method('spawn', force=True)

    from nicegui import ui, app
    from src.ui.pages.dashboard import build_dashboard
    from src.ui.pages.monitor import build_monitor

    # Configure native window (before ui.run)
    app.native.window_args.update({
        'frameless': True,
        'easy_drag': False,
        'background_color': '#0A0A0B',
    })
    app.native.settings['DRAG_REGION_SELECTOR'] = '.drag-handle'

    # Auto-load calibration matrix if available
    controller.load_calibration_matrix()

    @ui.page('/dashboard')
    def dashboard_page(token: str = ''):
        if token != DASHBOARD_TOKEN:
            ui.label('Access denied').classes('text-red-500 text-2xl p-8')
            return
        build_dashboard(state, controller)

    @ui.page('/monitor')
    def monitor_page():
        build_monitor(state, controller)

    @ui.page('/')
    def root_page():
        # Native window opens root — redirect to dashboard with token
        ui.navigate.to(f'/dashboard?token={DASHBOARD_TOKEN}')

    # Single global timer for telemetry polling (62.5 Hz)
    app.on_startup(lambda: ui.timer(0.016, _global_poll))

    print(f'Dashboard token: {DASHBOARD_TOKEN}')
    print(f'Monitor available at: http://<host>:8080/monitor')

    ui.run(
        native=True,
        host='0.0.0.0',
        port=8080,
        title='Cercus',
        window_size=(1400, 900),
        reload=False,
        frameless=True,
    )


if __name__ == '__main__':
    main()
