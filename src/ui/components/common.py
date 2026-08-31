"""Shared UI helpers used by both dashboard and monitor pages."""
from typing import Any


def fmt_val(v: Any) -> str:
    """Format a telemetry value for display."""
    if v is None:
        return '—'
    try:
        return f'{float(v):.2f}'
    except (ValueError, TypeError):
        return str(v)


# Phase dot / pill background — Tailwind classes
COLOR_MAP = {
    'cyan': 'bg-[#6EDBA1]',    # accent mint
    'lime': 'bg-[#8DB954]',    # ok olive
    'green': 'bg-[#8DB954]',   # ok olive
    'orange': 'bg-[#D4883A]',  # warn
    'red': 'bg-[#C75449]',     # err
    'gray': 'bg-[#2E2E2A]',    # border/muted
    'white': 'bg-[#E8E6E1]',   # text
    'yellow': 'bg-[#D4883A]',  # warn
}

# Phase dot / pill — raw hex values (for inline style= usage)
COLOR_HEX = {
    'cyan': '#6EDBA1', 'lime': '#8DB954', 'green': '#8DB954',
    'orange': '#D4883A', 'red': '#C75449', 'gray': '#807D75',
    'white': '#E8E6E1', 'yellow': '#D4883A',
}

# Worker badge states
WORKER_COLORS = {
    'running':      ('bg-[#8DB954]', 'RUNNING'),
    'worker_done':  ('bg-[#6EDBA1]', 'DONE'),
    'worker_abort': ('bg-[#C75449]', 'ABORTED'),
    'worker_error': ('bg-[#C75449]', 'ERROR'),
    'idle':         ('bg-[#2E2E2A]', 'IDLE'),
}


def color_pill(pill: Any, color_name: str) -> None:
    cls = COLOR_MAP.get(color_name, 'bg-[#2E2E2A]')
    # Dark text on bright pills, light text on dark pills
    text_cls = 'text-[#111110]' if color_name not in ('gray',) else 'text-[#807D75]'
    pill.classes(replace=f'mono text-[10px] font-bold px-2 py-0.5 rounded-full {cls} {text_cls}')


def update_worker_badge(badge: Any, status: str, error: str) -> None:
    bg, label = WORKER_COLORS.get(status, WORKER_COLORS['idle'])
    text = label + (f' · {error}' if error else '')
    badge.text = text
    # Dark text on bright badges, muted on idle
    text_cls = 'text-[#111110]' if status not in ('idle',) else 'text-[#807D75]'
    badge.classes(replace=f'mono text-[9px] font-bold px-2 py-0.5 rounded-full {bg} {text_cls}')


# Terminal status → (display text, CSS color var)
_TERMINAL_TEXT = {
    'worker_done':  ('Experiment completed', 'var(--ok)'),
    'worker_abort': ('ABORTED', 'var(--err)'),
}


def update_status_label(label: Any, state: Any, controller: Any) -> None:
    """Set status label text + color from shared state. Used by both pages."""
    # Use controller.terminal_status directly — state.worker_died is transient (16ms)
    if controller.terminal_status:
        status = controller.terminal_status
        if status == 'worker_error':
            err = controller.terminal_error or ''
            text = f'ERROR: {err}' if err else 'ERROR'
            color = 'var(--err)'
        else:
            text, color = _TERMINAL_TEXT.get(
                status, ('Worker disconnected', 'var(--err)')
            )
    else:
        text = state.status_text
        color = 'var(--warn)' if state.is_aborting else 'var(--text-muted)'
    label.text = text
    label.style(f'color: {color};')
