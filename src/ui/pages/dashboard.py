"""Dashboard page — /dashboard (token-gated, native window, full controls)."""
from nicegui import ui

from src.ui.components.config_panel import config_panel
from src.ui.components.calibration import calibration_panel
from src.ui.components.trajectory import trajectory_canvas
from src.ui.components.twin_preview import twin_preview_canvas, update_twin
from src.ui.components.verdict_table import verdict_table
from src.ui.components.hw_status import hw_status_panel
from src.ui.components.common import fmt_val, color_pill, update_worker_badge


def build_dashboard(state, controller):
    """Build the full dashboard UI. Called inside @ui.page handler."""
    from src.ui.theme import apply_theme
    apply_theme()

    # ── Two-column layout ──
    with ui.row().classes('w-full h-screen gap-0 no-wrap'):
        # ── Left column: config + controls (fixed 380px) ──
        with ui.column().classes('w-[380px] min-w-[380px] h-full overflow-y-auto p-4 gap-3 border-r border-[#262629]'):
            ui.label('Cercus').classes('text-xl font-bold text-cyan-400 mb-1')

            cfg_card, get_form_values = config_panel()
            calib = calibration_panel(controller)

            ui.separator()
            with ui.row().classes('w-full gap-2'):
                start_btn = ui.button('START', on_click=lambda: _start(controller, get_form_values, state, start_btn, stop_btn))
                start_btn.classes('flex-grow bg-green-700 text-white font-bold')
                stop_btn = ui.button('STOP', on_click=lambda: _stop(controller, stop_btn))
                stop_btn.classes('flex-grow bg-red-900 text-white font-bold')
                stop_btn.disable()

        # ── Right column: live status + visualizations (flex) ──
        with ui.column().classes('flex-grow h-full overflow-y-auto p-4 gap-3'):
            # Status bar
            with ui.row().classes('w-full items-center gap-3'):
                phase_pill = ui.label('IDLE').classes('mono text-xs font-bold px-2.5 py-1 rounded-full bg-zinc-700 text-zinc-900')
                sess_label = ui.label('session —').classes('mono text-xs text-zinc-400')
                trial_label = ui.label('trial — / —').classes('mono text-xs text-zinc-400')
                worker_badge = ui.label('IDLE').classes('mono text-[9px] font-bold px-2 py-0.5 rounded-full bg-zinc-700 text-zinc-400')
                status_label = ui.label('Ready').classes('text-xs text-zinc-400 ml-auto')

            # Twin preview
            with ui.card().classes('w-full'):
                ui.label('Stimulus Preview').classes('text-sm font-semibold text-zinc-300 mb-1')
                twin_container = twin_preview_canvas()

            # Trajectory + kinematic readouts
            with ui.card().classes('w-full'):
                ui.label('Trajectory').classes('text-sm font-semibold text-zinc-300 mb-1')
                with ui.row().classes('w-full gap-4'):
                    traj_container = trajectory_canvas(state)
                    traj_container.classes('w-[200px] h-[200px]')
                    with ui.column().classes('gap-1 justify-center'):
                        kin_angle = ui.label('θ: —').classes('mono text-xs text-zinc-300')
                        kin_turn = ui.label('ω: —').classes('mono text-xs text-zinc-300')
                        kin_disp = ui.label('D: —').classes('mono text-xs text-zinc-300')

            # Hardware state
            hw = hw_status_panel(state)

            # Verdict table
            verd = verdict_table(state)

    # ── Per-client UI sync (reads shared state, no queue polling) ──
    def tick():
        # Re-enable start button when worker dies
        if state.worker_died and not controller.worker_alive:
            start_btn.enable()
            stop_btn.disable()

        phase_pill.text = state.phase
        color_pill(phase_pill, state.ui_color)
        sess_label.text = f'session {state.session_num}'
        trial_label.text = f'trial {state.trial_idx} / {state.total_trials}'
        update_worker_badge(worker_badge, state.worker_status, state.worker_error)
        status_label.text = state.status_text

        km = state.kinematic
        kin_angle.text = f"θ: {fmt_val(km.get('k_angle'))}"
        kin_turn.text = f"ω: {fmt_val(km.get('k_turn_speed'))}"
        kin_disp.text = f"D: {fmt_val(km.get('k_disp'))}"

        verd._verdict_refresh()
        hw._hw_refresh()
        calib._calib_refresh()

    ui.timer(0.016, tick)

    # Trajectory + twin update at lower rate (50ms ≈ 20Hz)
    async def visual_tick():
        if hasattr(traj_container, '_traj_update'):
            await traj_container._traj_update()
        await update_twin(twin_container, state.ui_twin)

    ui.timer(0.05, visual_tick)


def _start(controller, get_form_values, state, start_btn, stop_btn):
    from src.ui.controller import ExperimentController
    form = get_form_values()
    config = ExperimentController.build_config(form)
    if controller.calib_matrix:
        config['calib_matrix'] = controller.calib_matrix
    state.reset()
    state.status_text = 'Running...'
    state.worker_status = 'running'
    state.config_snapshot = config  # populate for /monitor display
    controller.start_experiment(config)
    start_btn.disable()
    stop_btn.enable()


def _stop(controller, stop_btn):
    controller.stop_experiment()
    stop_btn.disable()
