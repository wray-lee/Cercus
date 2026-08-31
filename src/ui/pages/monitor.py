"""Monitor page — /monitor (read-only, browser-accessible, no controls)."""
from nicegui import ui

from src.ui.components.trajectory import trajectory_canvas
from src.ui.components.twin_preview import twin_preview_canvas, update_twin
from src.ui.components.verdict_table import verdict_table
from src.ui.components.hw_status import hw_status_panel
from src.ui.components.calibration import calibration_display


def build_monitor(state, controller):
    """Build the read-only monitor UI. Called inside @ui.page handler."""

    with ui.column().classes('w-full max-w-5xl mx-auto p-4 gap-3'):
        # Header
        with ui.row().classes('w-full items-center gap-3'):
            ui.label('Cercus Monitor').classes('text-lg font-bold text-cyan-400')
            phase_pill = ui.label('IDLE').classes('mono text-xs font-bold px-2.5 py-1 rounded-full bg-zinc-700 text-zinc-900')
            sess_label = ui.label('session —').classes('mono text-xs text-zinc-400')
            trial_label = ui.label('trial — / —').classes('mono text-xs text-zinc-400')
            worker_badge = ui.label('IDLE').classes('mono text-[9px] font-bold px-2 py-0.5 rounded-full bg-zinc-700 text-zinc-400')
            status_label = ui.label('Ready').classes('text-xs text-zinc-400 ml-auto')

        # Config snapshot (read-only)
        with ui.card().classes('w-full'):
            ui.label('Configuration').classes('text-sm font-semibold text-zinc-300 mb-1')
            config_grid = ui.element('div').classes('grid grid-cols-3 gap-2 text-xs')

        # Visuals row
        with ui.row().classes('w-full gap-3'):
            # Twin preview
            with ui.card().classes('flex-grow'):
                ui.label('Stimulus Preview').classes('text-sm font-semibold text-zinc-300 mb-1')
                twin_container = twin_preview_canvas()

            # Trajectory
            with ui.card():
                ui.label('Trajectory').classes('text-sm font-semibold text-zinc-300 mb-1')
                with ui.row().classes('gap-3'):
                    traj_container = trajectory_canvas(state)
                    traj_container.classes('w-[180px] h-[180px]')
                    with ui.column().classes('gap-1 justify-center'):
                        kin_angle = ui.label('θ: —').classes('mono text-xs text-zinc-300')
                        kin_turn = ui.label('ω: —').classes('mono text-xs text-zinc-300')
                        kin_disp = ui.label('D: —').classes('mono text-xs text-zinc-300')

        # Hardware + Calibration
        with ui.row().classes('w-full gap-3'):
            hw = hw_status_panel(state)
            hw.classes('flex-grow')
            calib_card = calibration_display(controller)
            calib_card.classes('flex-grow')

        # Verdict table
        verd = verdict_table(state)

    # ── Periodic UI update ──
    def tick():
        # Monitor reads the same shared state — controller.poll_telemetry()
        # is called by the dashboard's timer; monitor just reads state.
        # But if dashboard isn't open, we need to poll too.
        events = controller.poll_telemetry()
        state.apply(events)

        if state.worker_died:
            controller.cleanup_worker()

        phase_pill.text = state.phase
        _color_pill(phase_pill, state.ui_color)
        sess_label.text = f'session {state.session_num}'
        trial_label.text = f'trial {state.trial_idx} / {state.total_trials}'
        _update_worker_badge(worker_badge, state.worker_status, state.worker_error)
        status_label.text = state.status_text

        km = state.kinematic
        kin_angle.text = f"θ: {_fmt(km.get('k_angle'))}"
        kin_turn.text = f"ω: {_fmt(km.get('k_turn_speed'))}"
        kin_disp.text = f"D: {_fmt(km.get('k_disp'))}"

        verd._verdict_refresh()
        hw._hw_refresh()
        calib_card._calib_refresh()

        # Config snapshot
        _update_config_grid(config_grid, state.config_snapshot)

    ui.timer(0.016, tick)

    async def visual_tick():
        if hasattr(traj_container, '_traj_update'):
            await traj_container._traj_update()
        await update_twin(twin_container, state.ui_twin)

    ui.timer(0.05, visual_tick)


def _update_config_grid(grid, cfg):
    if not cfg:
        return
    grid.clear()
    display_keys = [
        'Paradigm Class', 'Experiment Pattern', 'Subject ID',
        'Session Number', 'Total Sessions', 'ITI Range (sec)', 'ISI Range (sec)',
    ]
    with grid:
        for k in display_keys:
            if k in cfg:
                with ui.element('div').classes('bg-[#0E0E11] rounded px-2 py-1'):
                    ui.label(k).classes('text-[10px] text-zinc-500')
                    ui.label(str(cfg[k])).classes('text-xs text-zinc-200')


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
