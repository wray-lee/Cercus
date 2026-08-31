"""Dashboard page — /dashboard (token-gated, native window, full controls)."""
from nicegui import ui

from src.ui.components.titlebar import titlebar
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

    # ── Frameless window layout: titlebar + body ──
    with ui.column().classes('w-full h-screen gap-0 overflow-hidden'):
        titlebar()

        # ── Main body: two columns ──
        with ui.row().classes('w-full flex-grow gap-0 overflow-hidden'):
            # ── Left column: config + controls (fixed 360px, scrollable) ──
            with ui.column().classes('w-[360px] min-w-[360px] h-full overflow-y-auto p-3 gap-2 border-r border-[#262629]'):
                cfg_card, get_form_values = config_panel()

                ui.separator()
                with ui.row().classes('w-full gap-2'):
                    start_btn = ui.button('START', on_click=lambda: _start(controller, get_form_values, state, start_btn, stop_btn))
                    start_btn.classes('flex-grow bg-green-700 text-white font-bold').props('dense')
                    stop_btn = ui.button('STOP', on_click=lambda: _stop(controller, stop_btn))
                    stop_btn.classes('flex-grow bg-red-900 text-white font-bold').props('dense')
                    stop_btn.disable()

            # ── Right column: live status + compact visualizations ──
            with ui.column().classes('flex-grow h-full overflow-y-auto p-3 gap-2'):
                # Status bar
                with ui.row().classes('w-full items-center gap-2 mb-1'):
                    # Status dot + phase
                    with ui.row().classes('items-center gap-1'):
                        phase_dot = ui.html('<span class="status-dot" style="background: #71717A;"></span>')
                        phase_pill = ui.label('IDLE').classes('mono text-xs font-bold text-zinc-300')
                    sess_label = ui.label('session —').classes('mono text-[10px] text-zinc-400')
                    trial_label = ui.label('trial — / —').classes('mono text-[10px] text-zinc-400')
                    worker_badge = ui.label('IDLE').classes('mono text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-zinc-700 text-zinc-400')
                    status_label = ui.label('Ready').classes('text-[10px] text-zinc-400 ml-auto')

                # Visuals row: stimulus + trajectory + kinematic readouts
                with ui.row().classes('w-full gap-2'):
                    # Twin preview (compact)
                    with ui.card().classes('flex-grow'):
                        ui.label('Stimulus').classes('text-xs font-semibold text-zinc-300 mb-1')
                        twin_container = twin_preview_canvas()
                        twin_container.style('max-height: 180px')

                    # Trajectory + kinematic (compact)
                    with ui.card().classes('w-[280px]'):
                        ui.label('Trajectory').classes('text-xs font-semibold text-zinc-300 mb-1')
                        with ui.row().classes('w-full gap-2'):
                            traj_container = trajectory_canvas(state)
                            traj_container.classes('w-[140px] h-[140px]')
                            with ui.column().classes('gap-0.5 justify-center'):
                                kin_angle = ui.label('θ: —').classes('mono text-[10px] text-zinc-300')
                                kin_turn = ui.label('ω: —').classes('mono text-[10px] text-zinc-300')
                                kin_disp = ui.label('D: —').classes('mono text-[10px] text-zinc-300')

                # Hardware state + Verdict table + Calibration (three columns)
                with ui.row().classes('w-full gap-2'):
                    hw = hw_status_panel(state)
                    hw.classes('flex-grow')
                    verd = verdict_table(state)
                    verd.classes('flex-grow')
                    calib = calibration_panel(controller)
                    calib.classes('w-[280px]')

    # ── Per-client UI sync (reads shared state, no queue polling) ──
    def tick():
        # Re-enable start button when worker dies
        if state.worker_died and not controller.worker_alive:
            start_btn.enable()
            stop_btn.disable()

        phase_pill.text = state.phase

        # Update status dot color based on phase
        dot_colors = {
            'cyan': '#22D3EE', 'lime': '#A3E635', 'green': '#10B981',
            'orange': '#FB923C', 'red': '#F87171', 'gray': '#71717A',
        }
        dot_color = dot_colors.get(state.ui_color, '#71717A')
        phase_dot.content = f'<span class="status-dot" style="background: {dot_color};"></span>'

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
        try:
            if hasattr(traj_container, '_traj_update'):
                await traj_container._traj_update()
            await update_twin(twin_container, state.ui_twin)
        except TimeoutError:
            pass  # Page disconnected, ignore

    visual_timer = ui.timer(0.05, visual_tick)

    # Cancel timers on disconnect to prevent errors on window close
    from nicegui import context
    context.client.on_disconnect(lambda: visual_timer.cancel())


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
