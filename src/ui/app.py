"""NiceGUI application entry point.

Run with: python -m src.ui.app
"""
import multiprocessing as mp
import secrets

from nicegui import ui, app

from src.ui.controller import ExperimentController
from src.ui.state import AppState
from src.ui.theme import apply_theme
from src.ui.pages.dashboard import build_dashboard
from src.ui.pages.monitor import build_monitor

# ── Shared state (single process, all clients see the same) ──
controller = ExperimentController()
state = AppState()

# ── Dashboard access token ──
DASHBOARD_TOKEN = secrets.token_urlsafe(32)


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


def main():
    mp.set_start_method('spawn', force=True)
    apply_theme()

    # Auto-load calibration matrix if available
    controller.load_calibration_matrix()

    # Configure native window to open dashboard with token
    app.native.window_args['url'] = f'/dashboard?token={DASHBOARD_TOKEN}'

    print(f'Dashboard token: {DASHBOARD_TOKEN}')
    print(f'Monitor available at: http://<host>:8080/monitor')

    ui.run(
        native=True,
        host='0.0.0.0',
        port=8080,
        title='Cercus · Experiment Dashboard',
        window_size=(1400, 900),
        reload=False,
    )


if __name__ == '__main__':
    main()
