"""Headless test: verify NiceGUI server starts without native window."""
import multiprocessing as mp
import os
import secrets
from threading import Thread
import time

from nicegui import app, ui
import pytest
import requests

from src.ui.controller import ExperimentController
from src.ui.pages.dashboard import build_dashboard
from src.ui.pages.monitor import build_monitor
from src.ui.state import AppState


def test_server_start() -> None:
    """Test that the server starts and responds on /monitor and /dashboard."""
    mp.set_start_method('spawn', force=True)

    controller = ExperimentController()
    state = AppState()
    DASHBOARD_TOKEN = secrets.token_urlsafe(32)

    controller.load_calibration_matrix()

    @ui.page('/dashboard')
    def dashboard_page(token: str = '') -> None:
        if token != DASHBOARD_TOKEN:
            ui.label('Access denied')
            return
        build_dashboard(state, controller)

    @ui.page('/monitor')
    def monitor_page() -> None:
        build_monitor(state, controller)

    @ui.page('/')
    def root_page() -> None:
        ui.navigate.to(f'/dashboard?token={DASHBOARD_TOKEN}')

    def _global_poll() -> None:
        events = controller.poll_telemetry()
        state.apply(events)

    app.on_startup(lambda: ui.timer(0.016, _global_poll))

    # Start server in background thread
    def run_server() -> None:
        # Temporarily remove PYTEST_CURRENT_TEST so NiceGUI starts the actual Uvicorn server
        pytest_env = os.environ.pop('PYTEST_CURRENT_TEST', None)
        try:
            ui.run(
                native=False,  # Disable native window for headless test
                host='127.0.0.1',
                port=8765,
                reload=False,
                show=False,
            )
        finally:
            if pytest_env is not None:
                os.environ['PYTEST_CURRENT_TEST'] = pytest_env

    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to start
    time.sleep(3)

    # Test endpoints
    try:
        # Test /monitor endpoint
        resp_mon = requests.get('http://127.0.0.1:8765/monitor', timeout=5)
        assert resp_mon.status_code == 200
        assert 'text/html' in resp_mon.headers.get('content-type', '')
        print('[OK] /monitor page rendered successfully')

        # Test /dashboard with token
        resp_dash = requests.get(f'http://127.0.0.1:8765/dashboard?token={DASHBOARD_TOKEN}', timeout=5)
        assert resp_dash.status_code == 200
        assert 'Access denied' not in resp_dash.text
        print('[OK] /dashboard page rendered successfully with token')

        # Test /dashboard without token
        resp_denied = requests.get('http://127.0.0.1:8765/dashboard', timeout=5)
        assert resp_denied.status_code == 200
        assert 'Access denied' in resp_denied.text
        print('[OK] /dashboard correctly denied without token')
    except Exception as e:
        pytest.fail(f'Server request failed: {e}')


if __name__ == '__main__':
    test_server_start()
    exit(0)
