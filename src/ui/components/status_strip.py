"""Shared status strip + tick loop — used by both dashboard and monitor."""
from typing import Any, Callable, Dict, Optional
from nicegui import ui

from src.ui.components.common import (
    fmt_val, update_worker_badge, update_status_label, COLOR_HEX,
)


# ── SVG progress ring ──
def _make_progress_ring(pct):
    r = 9
    c = 2 * 3.14159 * r
    fill = c * pct
    return (
        f'<svg width="24" height="24" viewBox="0 0 24 24">'
        f'<circle cx="12" cy="12" r="{r}" fill="none" stroke="var(--border)" stroke-width="3"/>'
        f'<circle cx="12" cy="12" r="{r}" fill="none" stroke="var(--accent)" stroke-width="3" '
        f'stroke-linecap="round" stroke-dasharray="{fill:.2f} {c:.2f}" '
        f'transform="rotate(-90 12 12)"/>'
        f'</svg>'
    )


# ── Segmented trial progress bar ──
def _make_trial_bar(current, total):
    if total <= 0:
        return ''
    n = min(total, 80)
    scaled = int(current * n / total) if total > 0 else 0
    segs = []
    for i in range(n):
        color = 'var(--accent)' if i < scaled else 'var(--border)'
        segs.append(
            f'<span style="flex:1;height:4px;border-radius:1px;background:{color};"></span>'
        )
    return f'<div style="display:flex;gap:1px;width:100%;">{" ".join(segs)}</div>'


def build_status_strip(*, show_subject: bool = False) -> Dict[str, Any]:
    """Build the status strip row and return a dict of widget references.

    Parameters
    ----------
    show_subject : bool
        If True, include Subject ID and Pattern labels (dashboard only).
    """
    widgets = {}
    with ui.row().classes('w-full items-center gap-3 status-strip'):
        widgets['live_badge'] = ui.label('IDLE').classes(
            'mono text-[9px] font-bold px-1.5 py-0.5 rounded'
        ).style('background: var(--border); color: var(--text-muted);')

        with ui.row().classes('items-center gap-1.5'):
            widgets['phase_dot'] = ui.html(
                '<span class="status-dot" style="background: var(--text-muted);"></span>'
            )
            widgets['phase_pill'] = ui.label('IDLE').classes(
                'mono text-[11px] font-bold'
            ).style('color: var(--text-muted);')

        if show_subject:
            widgets['subject_label'] = ui.label('—').classes(
                'mono text-[10px] font-semibold'
            ).style('color: var(--text);')
            widgets['pattern_label'] = ui.label('').classes(
                'text-[9px]'
            ).style('color: var(--text-muted);')

        with ui.row().classes('items-center gap-1'):
            widgets['sess_ring'] = ui.html(_make_progress_ring(0)).style(
                'width: 24px; height: 24px; flex-shrink: 0;'
            )
            widgets['sess_label'] = ui.label('session —').classes(
                'mono text-[10px]'
            ).style('color: var(--text-muted);')

        with ui.column().classes('gap-0.5'):
            widgets['trial_label'] = ui.label('trial — / —').classes(
                'mono text-[10px]'
            ).style('color: var(--text-muted);')
            widgets['trial_bar'] = ui.html('').style('height: 4px; min-width: 60px;')

        widgets['worker_badge'] = ui.label('IDLE').classes(
            'mono text-[9px] font-bold px-2 py-0.5 rounded-full'
        ).style('background: var(--border); color: var(--text-muted);')

        widgets['status_label'] = ui.label('Ready').classes(
            'text-[10px] ml-auto'
        ).style('color: var(--text-muted);')

    return widgets


def create_tick(
    state: Any,
    controller: Any,
    widgets: Dict[str, Any],
    *,
    extra_components: Optional[Dict[str, Any]] = None,
    favicon_fn: Optional[Callable[[bool], None]] = None,
) -> Callable[[], None]:
    """Create the optimized tick function with cache-based DOM updates.

    Parameters
    ----------
    state : AppState
    controller : ExperimentController
    widgets : dict from build_status_strip()
    extra_components : dict, optional
        Keys: 'hw', 'verd', 'calib', 'config_grid',
              'kin_angle', 'kin_turn', 'kin_disp'
    favicon_fn : callable(bool), optional
        Called every ~2s with is_running.

    Returns
    -------
    tick : callable for ui.timer
    """
    w = widgets
    ec = extra_components or {}
    _n = {'n': 0}
    _cache = {}

    def tick() -> None:
        _n['n'] += 1
        n = _n['n']

        # Phase pill
        if _cache.get('phase') != state.phase:
            _cache['phase'] = state.phase
            w['phase_pill'].text = state.phase

        # Status dot color
        raw_color = state.ui_color or 'gray'
        if _cache.get('color') != raw_color:
            _cache['color'] = raw_color
            dot_color = raw_color if raw_color.startswith('#') else COLOR_HEX.get(raw_color, '#807D75')
            is_active = raw_color not in ('gray', None, '')
            active_cls = ' active' if is_active else ''
            w['phase_dot'].content = (
                f'<span class="status-dot{active_cls}" '
                f'style="background: {dot_color}; color: {dot_color};"></span>'
            )
            w['phase_pill'].style(f'color: {dot_color};')
            if is_active:
                w['phase_pill'].classes(add='phase-glow')
            else:
                w['phase_pill'].classes(remove='phase-glow')

        # Subject / pattern (dashboard only)
        if 'subject_label' in w:
            cfg = state.config_snapshot
            subj = cfg.get('Subject ID', '—') if cfg else '—'
            if _cache.get('subj') != subj:
                _cache['subj'] = subj
                w['subject_label'].text = subj
            patt = cfg.get('Experiment Pattern', '') if cfg else ''
            if _cache.get('patt') != patt:
                _cache['patt'] = patt
                w['pattern_label'].text = patt

        # Session ring
        sess_key = state.session_num
        if _cache.get('sess') != sess_key:
            _cache['sess'] = sess_key
            w['sess_label'].text = f'session {sess_key}'
            cfg = state.config_snapshot
            total_sess = cfg.get('Total Sessions', 0) if cfg else 0
            try:
                pct = min(1.0, int(sess_key) / int(total_sess)) if int(total_sess) > 0 else 0
            except (ValueError, TypeError):
                pct = 0
            w['sess_ring'].content = _make_progress_ring(pct)

        # Trial bar
        trial_key = (state.trial_idx, state.total_trials)
        if _cache.get('trial') != trial_key:
            _cache['trial'] = trial_key
            w['trial_label'].text = f'trial {trial_key[0]} / {trial_key[1]}'
            try:
                t_idx, t_tot = int(trial_key[0]), int(trial_key[1])
            except (ValueError, TypeError):
                t_idx, t_tot = 0, 0
            w['trial_bar'].content = _make_trial_bar(t_idx, t_tot)

        # Worker badge
        wb_key = (state.worker_status, state.worker_error)
        if _cache.get('wb') != wb_key:
            _cache['wb'] = wb_key
            update_worker_badge(w['worker_badge'], state.worker_status, state.worker_error)

        # Live indicator
        is_running = state.worker_status == 'running'
        if _cache.get('live') != is_running:
            _cache['live'] = is_running
            if is_running:
                w['live_badge'].text = 'LIVE · 30Hz'
                w['live_badge'].style('background: var(--ok); color: var(--bg);')
            else:
                w['live_badge'].text = 'IDLE'
                w['live_badge'].style('background: var(--border); color: var(--text-muted);')

        # Status text
        st_key = (controller.terminal_status, controller.terminal_error,
                  state.status_text, state.is_aborting)
        if _cache.get('st') != st_key:
            _cache['st'] = st_key
            update_status_label(w['status_label'], state, controller)

        # Kinematic readouts
        if 'kin_angle' in ec:
            km = state.kinematic
            km_key = (km.get('k_angle'), km.get('k_turn_speed'), km.get('k_disp'))
            if _cache.get('km') != km_key:
                _cache['km'] = km_key
                ec['kin_angle'].text = f"θ: {fmt_val(km_key[0])}"
                ec['kin_turn'].text = f"ω: {fmt_val(km_key[1])}"
                ec['kin_disp'].text = f"D: {fmt_val(km_key[2])}"

        # ── Heavy refreshes — throttled ──
        if n % 6 == 0 and 'hw' in ec:
            ec['hw']._hw_refresh()
        if n % 16 == 0:
            if 'verd' in ec:
                ec['verd']._verdict_refresh()
            if 'calib' in ec:
                ec['calib']._calib_refresh()
            if 'config_grid' in ec:
                _update_config_grid = ec.get('_update_config_grid')
                if _update_config_grid:
                    _update_config_grid(ec['config_grid'], state.config_snapshot)
        if n % 125 == 0 and favicon_fn:
            favicon_fn(is_running)

    return tick
