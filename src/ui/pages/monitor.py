"""Monitor page — /monitor (read-only, browser-accessible, no controls)."""
from nicegui import ui

from src.ui.components.trajectory import trajectory_canvas
from src.ui.components.twin_preview import twin_preview_canvas, update_twin
from src.ui.components.verdict_table import verdict_table
from src.ui.components.hw_status import hw_status_panel
from src.ui.components.calibration import calibration_display
from src.ui.components.common import fmt_val, color_pill, update_worker_badge


def build_monitor(state, controller):
    """Build the read-only monitor UI. Called inside @ui.page handler.

    Polling is handled by the global app.timer in app.py — this page
    only reads shared state and updates its own widgets.
    """

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

    # ── Per-client UI sync (reads shared state, no queue polling) ──
    def tick():
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
        calib_card._calib_refresh()
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
