"""NiceGUI application entry point.

Run with: python main.py

NiceGUI script mode detects any UI element created at module/global scope.
If ui.page decorators are also present, it raises RuntimeError. Therefore:
- All ui.page definitions go inside main()
- No UI calls (ui.add_css, ui.dark_mode, etc.) at global scope
- Theme is applied per-page inside build_dashboard / build_monitor
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
        controller.cleanup_worker()


def main():
    mp.set_start_method('spawn', force=True)

    from nicegui import ui, app
    from src.ui.pages.dashboard import build_dashboard
    from src.ui.pages.monitor import build_monitor

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
        ui.navigate.to('/monitor')

    # Single global timer for telemetry polling (62.5 Hz)
    app.on_startup(lambda: ui.timer(0.016, _global_poll))

    print(f'Dashboard token: {DASHBOARD_TOKEN}')
    print(f'Monitor available at: http://<host>:8080/monitor')

    ui.run(
        native=True,
        native_url=f'/dashboard?token={DASHBOARD_TOKEN}',
        host='0.0.0.0',
        port=8080,
        title='Cercus · Experiment Dashboard',
        window_size=(1400, 900),
        reload=False,
    )


if __name__ == '__main__':
    main()
