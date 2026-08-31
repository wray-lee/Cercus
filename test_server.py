"""Headless test: verify NiceGUI server starts without native window."""
import multiprocessing as mp
import time
import requests
from threading import Thread

from src.ui.controller import ExperimentController
from src.ui.state import AppState


def test_server_start():
    """Test that the server starts and responds on /monitor."""
    mp.set_start_method('spawn', force=True)

    from nicegui import ui, app
    from src.ui.pages.dashboard import build_dashboard
    from src.ui.pages.monitor import build_monitor
    import secrets

    controller = ExperimentController()
    state = AppState()
    DASHBOARD_TOKEN = secrets.token_urlsafe(32)

    controller.load_calibration_matrix()

    @ui.page('/dashboard')
    def dashboard_page(token: str = ''):
        if token != DASHBOARD_TOKEN:
            ui.label('Access denied')
            return
        build_dashboard(state, controller)

    @ui.page('/monitor')
    def monitor_page():
        build_monitor(state, controller)

    @ui.page('/')
    def root_page():
        ui.navigate.to(f'/dashboard?token={DASHBOARD_TOKEN}')

    def _global_poll():
        events = controller.poll_telemetry()
        state.apply(events)

    app.on_startup(lambda: ui.timer(0.016, _global_poll))

    # Start server in background thread
    def run_server():
        ui.run(
            native=False,  # Disable native window for headless test
            host='127.0.0.1',
            port=8765,
            reload=False,
            show=False,
        )

    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to start
    time.sleep(3)

    # Test /monitor endpoint
    try:
        resp = requests.get('http://127.0.0.1:8765/monitor', timeout=5)
        print(f'[OK] Server responded: HTTP {resp.status_code}')
        print(f'[OK] Content-Type: {resp.headers.get("content-type")}')
        print(f'[OK] Response size: {len(resp.text)} bytes')
        if resp.status_code == 200 and 'text/html' in resp.headers.get('content-type', ''):
            print('[OK] /monitor page rendered successfully')
            return True
        else:
            print(f'[FAIL] Unexpected response: {resp.status_code}')
            return False
    except Exception as e:
        print(f'[FAIL] Server request failed: {e}')
        return False


if __name__ == '__main__':
    success = test_server_start()
    exit(0 if success else 1)
