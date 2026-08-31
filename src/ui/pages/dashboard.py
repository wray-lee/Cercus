"""Dashboard page — /dashboard (token-gated, native window, full controls)."""
import json
from nicegui import ui, app

from src.ui.components.config_panel import config_panel
from src.ui.components.calibration import calibration_panel
from src.ui.components.trajectory import trajectory_canvas
from src.ui.components.twin_preview import twin_preview_canvas, update_twin
from src.ui.components.verdict_table import verdict_table
from src.ui.components.hw_status import hw_status_panel


def build_dashboard(state, controller):
    """Build the full dashboard UI. Called inside @ui.page handler."""

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

    # ── Periodic UI update (16ms ≈ 60Hz) ──
    def tick():
        events = controller.poll_telemetry()
        state.apply(events)

        # Handle worker death
        if state.worker_died:
            terminal = events.get('terminal')
            if terminal:
                action = terminal.get('action', '')
                controller.terminal_status = action
                controller.terminal_error = terminal.get('error', '')
            controller.cleanup_worker()
            start_btn.enable()
            stop_btn.disable()

        # Update phase pill
        phase_pill.text = state.phase
        _color_pill(phase_pill, state.ui_color)

        # Session / trial
        sess_label.text = f'session {state.session_num}'
        trial_label.text = f'trial {state.trial_idx} / {state.total_trials}'

        # Worker badge
        _update_worker_badge(worker_badge, state.worker_status, state.worker_error)
        status_label.text = state.status_text

        # Kinematic readouts
        km = state.kinematic
        kin_angle.text = f"θ: {_fmt(km.get('k_angle'))}"
        kin_turn.text = f"ω: {_fmt(km.get('k_turn_speed'))}"
        kin_disp.text = f"D: {_fmt(km.get('k_disp'))}"

        # Component refreshes
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
    controller.start_experiment(config)
    start_btn.disable()
    stop_btn.enable()


def _stop(controller, stop_btn):
    controller.stop_experiment()
    stop_btn.disable()


def _fmt(v):
    if v is None:
        return '—'
    try:
        return f'{float(v):.2f}'
    except (ValueError, TypeError):
        return str(v)


def _color_pill(pill, color_name):
    color_map = {
        'cyan': 'bg-cyan-500', 'lime': 'bg-lime-500', 'green': 'bg-green-500',
        'orange': 'bg-orange-500', 'red': 'bg-red-500', 'gray': 'bg-zinc-700',
        'white': 'bg-zinc-300', 'yellow': 'bg-yellow-500',
    }
    cls = color_map.get(color_name, 'bg-zinc-700')
    pill.classes(replace=f'mono text-xs font-bold px-2.5 py-1 rounded-full {cls} text-zinc-900')


WORKER_COLORS = {
    'running': ('bg-lime-500', 'RUNNING'),
    'worker_done': ('bg-cyan-500', 'DONE'),
    'worker_abort': ('bg-orange-500', 'ABORTED'),
    'worker_error': ('bg-red-500', 'ERROR'),
    'idle': ('bg-zinc-700', 'IDLE'),
}


def _update_worker_badge(badge, status, error):
    bg, label = WORKER_COLORS.get(status, WORKER_COLORS['idle'])
    text = label + (f' · {error}' if error else '')
    badge.text = text
    badge.classes(replace=f'mono text-[9px] font-bold px-2 py-0.5 rounded-full {bg} text-zinc-900')
