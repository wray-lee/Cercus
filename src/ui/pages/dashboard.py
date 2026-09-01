"""Dashboard page — /dashboard (token-gated, native window, full controls)."""
from nicegui import ui

from src.ui.controller import ExperimentController
from src.ui.state import AppState
from src.ui.components.titlebar import titlebar
from src.ui.components.config_panel import config_panel
from src.ui.components.calibration import calibration_panel
from src.ui.components.trajectory import trajectory_canvas
from src.ui.components.twin_preview import twin_preview_canvas, update_twin
from src.ui.components.verdict_table import verdict_table
from src.ui.components.hw_status import hw_status_panel
from src.ui.components.status_strip import build_status_strip, create_tick


def build_dashboard(state: AppState, controller: ExperimentController) -> None:
    """Build the full dashboard UI. Called inside @ui.page handler."""
    from src.ui.theme import apply_theme
    apply_theme()

    # ── Frameless window layout: titlebar + body ──
    with ui.column().classes('w-full h-screen gap-0 overflow-hidden'):
        titlebar()

        # ── Main body: two columns ──
        with ui.row().classes('w-full flex-grow gap-0').style('min-height: 0; overflow: hidden;'):

            # ── Left column: config + controls ──
            with ui.column().classes(
                'h-full overflow-y-auto p-3 gap-2'
            ).style(
                'width: 340px; min-width: 260px; flex-shrink: 1; '
                'border-right: 1px solid var(--border);'
            ):
                cfg_card, get_form_values = config_panel()

                ui.separator().classes('my-1').style('border-color: var(--border);')
                with ui.row().classes('w-full gap-2'):
                    start_btn = ui.button(
                        'START',
                        on_click=lambda: _start(controller, get_form_values, state, start_btn, stop_btn, _btn_state),
                    ).classes('flex-grow font-bold').style(
                        'background: #22A55B; color: #fff;'
                    ).props('dense unelevated')
                    stop_btn = ui.button(
                        'STOP',
                        on_click=lambda: _stop(controller, state, stop_btn),
                    ).classes('flex-grow font-bold').style(
                        'background: #E03C31; color: #fff;'
                    ).props('dense unelevated')
                    stop_btn.disable()

            # ── Sync button state with worker on page load/refresh ──
            _btn_state = {'started': False}
            if controller.worker_alive:
                _btn_state['started'] = True
                start_btn.disable()
                stop_btn.enable()

            # ── Right column: live status + compact visualizations ──
            with ui.column().classes('h-full overflow-y-auto p-3 gap-2').style(
                'flex: 1 1 0%; min-width: 0;'
            ):
                # ── Status strip ──
                strip = build_status_strip(show_subject=True)

                # ── Stimulus + Trajectory side by side ──
                with ui.row().classes('w-full gap-2 items-stretch').style('min-width: 0;'):
                    with ui.card().classes('min-w-0 flex flex-col').style('flex: 2 1 0%;'):
                        with ui.row().classes('items-center gap-1.5 mb-1'):
                            ui.icon('monitor').classes('text-[14px]').style('color: var(--text-muted);')
                            ui.label('Stimulus').classes('sec-title')
                        twin_container = twin_preview_canvas()

                    with ui.card().classes('min-w-0 flex flex-col').style(
                        'flex: 1 1 0%; min-width: 200px;'
                    ):
                        with ui.row().classes('items-center gap-1.5 mb-1'):
                            ui.icon('route').classes('text-[14px]').style('color: var(--text-muted);')
                            ui.label('Trajectory').classes('sec-title')
                        traj_container = trajectory_canvas(state)
                        with ui.row().classes('w-full gap-2 justify-center mt-1'):
                            kin_angle = ui.label('θ: —').classes(
                                'mono text-[10px] font-semibold'
                            ).style('color: var(--accent);')
                            kin_turn = ui.label('ω: —').classes(
                                'mono text-[10px] font-semibold'
                            ).style('color: var(--ok);')
                            kin_disp = ui.label('D: —').classes(
                                'mono text-[10px] font-semibold'
                            ).style('color: var(--warn);')

                # ── Hardware + Verdicts + Calibration ──
                with ui.row().classes('w-full gap-2').style('flex-wrap: wrap; min-width: 0;'):
                    hw = hw_status_panel(state)
                    hw.style('flex: 1 1 200px; min-width: 0;')
                    verd = verdict_table(state)
                    verd.style('flex: 1 1 200px; min-width: 0;')
                    calib = calibration_panel(controller)
                    calib.style('flex: 1 1 200px; min-width: 0;')

    # ── Dynamic favicon ──
    _setup_favicon()

    # ── Re-enable start on worker death (dashboard-only) ──
    # _btn_state was initialized above (line ~50) synced with controller.worker_alive

    def _check_worker_death():
        # Use controller.worker_alive directly — state.worker_died is transient (16ms)
        if _btn_state['started'] and not controller.worker_alive:
            _btn_state['started'] = False
            start_btn.enable()
            stop_btn.disable()

    # ── Shared tick loop ──
    tick = create_tick(
        state, controller, strip,
        extra_components={
            'hw': hw, 'verd': verd, 'calib': calib,
            'kin_angle': kin_angle, 'kin_turn': kin_turn, 'kin_disp': kin_disp,
        },
        favicon_fn=_update_favicon,
    )

    def dashboard_tick() -> None:
        _check_worker_death()
        tick()

    tick_timer = ui.timer(0.033, dashboard_tick)

    # Trajectory + twin update at lower rate (50ms ≈ 20Hz)
    async def visual_tick() -> None:
        try:
            if hasattr(traj_container, '_traj_update'):
                await traj_container._traj_update()
            await update_twin(twin_container, state.ui_twin)
        except Exception:
            pass

    visual_timer = ui.timer(0.05, visual_tick)

    from nicegui import context
    context.client.on_disconnect(lambda: (tick_timer.cancel(), visual_timer.cancel()))


# ── Favicon helpers ──
def _setup_favicon():
    ui.add_head_html('''
    <script>
    window._cercusFavicon = function(running) {
        const c = document.createElement('canvas'); c.width=32; c.height=32;
        const x = c.getContext('2d');
        x.clearRect(0,0,32,32);
        x.fillStyle = running ? '#C75449' : '#6EDBA1';
        x.beginPath(); x.arc(16,16,13,0,Math.PI*2); x.fill();
        if (!running) { x.fillStyle='#111110'; x.beginPath(); x.arc(16,16,5,0,Math.PI*2); x.fill(); }
        let link = document.querySelector('link[rel*="icon"]');
        if (!link) { link = document.createElement('link'); link.rel='icon'; document.head.appendChild(link); }
        link.href = c.toDataURL();
    };
    </script>
    ''')


def _update_favicon(is_running):
    try:
        ui.run_javascript(f'window._cercusFavicon && window._cercusFavicon({"true" if is_running else "false"})')
    except Exception:
        pass


def _start(controller, get_form_values, state, start_btn, stop_btn, btn_state):
    # Guard: don't reset state if worker is already running (e.g. page refresh)
    if controller.worker_alive:
        return
    from src.ui.controller import ExperimentController
    import logging
    log = logging.getLogger(__name__)
    try:
        form = get_form_values()
        config = ExperimentController.build_config(form)
        if controller.calib_matrix:
            config['calib_matrix'] = controller.calib_matrix
        state.reset()
        state.status_text = 'Running...'
        state.worker_status = 'running'
        state.config_snapshot = config
        controller.start_experiment(config)
    except Exception as exc:
        log.error('start_experiment failed: %s', exc, exc_info=True)
        state.status_text = f'Start failed: {exc}'
        state.worker_status = 'worker_error'
        state.worker_error = str(exc)
        start_btn.enable()
        stop_btn.disable()
        return
    btn_state['started'] = True
    start_btn.disable()
    stop_btn.enable()
    _yield_focus_to_psychopy()


def _stop(controller, state, stop_btn):
    controller.stop_experiment()
    state.set_aborting()
    stop_btn.disable()
    # Do NOT enable start_btn here — _check_worker_death() does it
    # once the worker process has actually terminated.


def _yield_focus_to_psychopy():
    """Yield foreground focus to PsychoPy without hiding the dashboard."""
    import sys
    if sys.platform != 'win32':
        return
    import threading, time

    def _do():
        time.sleep(1.5)
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            user32.FindWindowW.restype = ctypes.wintypes.HWND
            user32.FindWindowW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR]
            user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = ctypes.wintypes.BOOL
            hwnd = user32.FindWindowW(None, 'Cercus')
            if not hwnd:
                return  # Window not found — don't touch unrelated windows
            user32.ShowWindow(hwnd, 6)   # SW_MINIMIZE
            time.sleep(0.8)
            user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
        except Exception:
            pass

    threading.Thread(target=_do, daemon=True).start()
