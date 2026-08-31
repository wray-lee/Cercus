"""Monitor page — /monitor (read-only, browser-accessible, no controls)."""
from nicegui import ui

from src.ui.controller import ExperimentController
from src.ui.state import AppState
from src.ui.components.trajectory import trajectory_canvas
from src.ui.components.twin_preview import twin_preview_canvas, update_twin
from src.ui.components.verdict_table import verdict_table
from src.ui.components.hw_status import hw_status_panel
from src.ui.components.calibration import calibration_display
from src.ui.components.status_strip import build_status_strip, create_tick


def build_monitor(state: AppState, controller: ExperimentController) -> None:
    """Build the read-only monitor UI. Called inside @ui.page handler."""
    from src.ui.theme import apply_theme
    apply_theme()

    with ui.column().classes('w-full p-4 gap-3').style('min-height: 100vh;'):
        # ── Header + shared status strip ──
        ui.label('Cercus Monitor').classes('text-sm font-bold mb-1').style('color: var(--accent);')
        strip = build_status_strip(show_subject=False)

        # ── Main grid: 2×2 on wide screens, stacks on narrow ──
        with ui.element('div').classes('w-full').style(
            'display: grid; gap: 12px; '
            'grid-template-columns: repeat(auto-fit, minmax(min(100%, 480px), 1fr));'
        ):
            # Stimulus Preview
            with ui.card().classes('flex flex-col'):
                ui.label('Stimulus Preview').classes('sec-title mb-1')
                twin_container = twin_preview_canvas()

            # Trajectory + Kinematic
            with ui.card().classes('flex flex-col'):
                ui.label('Trajectory').classes('sec-title mb-1')
                traj_container = trajectory_canvas(state)
                with ui.row().classes('w-full gap-2 justify-center mt-1'):
                    kin_angle = ui.label('θ: —').classes('mono text-[10px] font-semibold').style('color: var(--accent);')
                    kin_turn = ui.label('ω: —').classes('mono text-[10px] font-semibold').style('color: var(--ok);')
                    kin_disp = ui.label('D: —').classes('mono text-[10px] font-semibold').style('color: var(--warn);')

            # Hardware
            hw = hw_status_panel(state)

            # Calibration
            calib_card = calibration_display(controller)

        # ── Bottom: Config + Verdicts side by side ──
        with ui.row().classes('w-full gap-3').style('flex-wrap: wrap; min-width: 0;'):
            # Config snapshot (responsive grid: 2 cols on mobile, 3-4 on desktop)
            with ui.card().style('flex: 1 1 400px; min-width: 0;'):
                ui.label('Configuration').classes('sec-title mb-1')
                config_grid = ui.element('div').style(
                    'display: grid; gap: 8px; font-size: 11px; '
                    'grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));'
                )

            # Verdict table
            verd = verdict_table(state)
            verd.style('flex: 1 1 360px; min-width: 0;')

    # ── Shared tick loop (same as dashboard, zero duplication) ──
    tick = create_tick(
        state, controller, strip,
        extra_components={
            'hw': hw, 'verd': verd, 'calib': calib_card,
            'kin_angle': kin_angle, 'kin_turn': kin_turn, 'kin_disp': kin_disp,
            'config_grid': config_grid,
            '_update_config_grid': _update_config_grid,
        },
    )
    tick_timer = ui.timer(0.033, tick)

    # Canvas updates at 20Hz
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


# Keys to hide from monitor (internal / uninteresting)
_HIDDEN_KEYS = {'_output_dir', 'calib_matrix', 'Sync Topology'}


def _update_config_grid(grid, cfg):
    if not cfg:
        return
    # Cache check — skip rebuild if config hasn't changed
    prev = getattr(grid, '_last_cfg', None)
    if prev is not None and prev == cfg:
        return
    grid._last_cfg = dict(cfg)
    grid.clear()
    with grid:
        for k, v in cfg.items():
            if k in _HIDDEN_KEYS:
                continue
            v_str = str(v)
            if len(v_str) > 80:
                v_str = v_str[:77] + '…'
            with ui.element('div').classes('cell rounded px-2 py-1'):
                ui.label(k).classes('text-[10px]').style('color: var(--text-muted);')
                ui.label(v_str).classes('text-xs mono').style('color: var(--text);')
