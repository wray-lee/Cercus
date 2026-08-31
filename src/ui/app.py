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
    terminal = events.get('terminal')
    if terminal:
        controller.terminal_status = terminal.get('action', '')
        controller.terminal_error = terminal.get('error', '')

    state.apply(events)

    if state.worker_died:
        if not controller.terminal_status:
            # Worker died without sending a terminal event
            controller.terminal_status = 'worker_error'
            controller.terminal_error = 'Worker process exited unexpectedly'
        state.worker_status = controller.terminal_status
        state.worker_error = controller.terminal_error
        controller.cleanup_worker()


def main() -> None:
    mp.set_start_method('spawn', force=True)

    from nicegui import ui, app
    from src.ui.pages.dashboard import build_dashboard
    from src.ui.pages.monitor import build_monitor

    # Configure native window (before ui.run)
    app.native.window_args.update({
        'frameless': True,
        'easy_drag': False,
        'background_color': '#111110',
    })
    app.native.settings['DRAG_REGION_SELECTOR'] = '.drag-handle'

    # Auto-load calibration matrix if available
    controller.load_calibration_matrix()

    @ui.page('/dashboard')
    def dashboard_page(token: str = '') -> None:
        if token != DASHBOARD_TOKEN:
            ui.label('Access denied').classes('text-red-500 text-2xl p-8')
            return
        build_dashboard(state, controller)

    @ui.page('/monitor')
    def monitor_page() -> None:
        build_monitor(state, controller)

    @ui.page('/')
    def root_page() -> None:
        from starlette.requests import Request
        request = ui.context.client.request
        # Native window (pywebview) connects from localhost — allow dashboard
        host = request.client.host if request.client else ''
        if host in ('127.0.0.1', '::1', 'localhost'):
            ui.navigate.to(f'/dashboard?token={DASHBOARD_TOKEN}')
        else:
            # Remote users get the read-only monitor
            ui.navigate.to('/monitor')

    # Single global timer for telemetry polling (30 Hz)
    # Must use app.timer (not ui.timer) so it runs globally, not per-client
    app.on_startup(lambda: app.timer(0.033, _global_poll))

    print(f'Dashboard token: {DASHBOARD_TOKEN}')
    print(f'Monitor available at: http://<host>:8000/monitor')

    ui.run(
        native=True,
        host='0.0.0.0',
        port=8000,
        title='Cercus',
        window_size=(1400, 900),
        reload=False,
        frameless=True,
    )


if __name__ == '__main__':
    main()
