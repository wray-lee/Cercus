"""Shared UI helpers used by both dashboard and monitor pages."""


def fmt_val(v):
    """Format a telemetry value for display."""
    if v is None:
        return '—'
    try:
        return f'{float(v):.2f}'
    except (ValueError, TypeError):
        return str(v)


COLOR_MAP = {
    'cyan': 'bg-cyan-500', 'lime': 'bg-lime-500', 'green': 'bg-green-500',
    'orange': 'bg-orange-500', 'red': 'bg-red-500', 'gray': 'bg-zinc-700',
    'white': 'bg-zinc-300', 'yellow': 'bg-yellow-500',
}

WORKER_COLORS = {
    'running': ('bg-lime-500', 'RUNNING'),
    'worker_done': ('bg-cyan-500', 'DONE'),
    'worker_abort': ('bg-orange-500', 'ABORTED'),
    'worker_error': ('bg-red-500', 'ERROR'),
    'idle': ('bg-zinc-700', 'IDLE'),
}


def color_pill(pill, color_name):
    cls = COLOR_MAP.get(color_name, 'bg-zinc-700')
    pill.classes(replace=f'mono text-xs font-bold px-2.5 py-1 rounded-full {cls} text-zinc-900')


def update_worker_badge(badge, status, error):
    bg, label = WORKER_COLORS.get(status, WORKER_COLORS['idle'])
    text = label + (f' · {error}' if error else '')
    badge.text = text
    badge.classes(replace=f'mono text-[9px] font-bold px-2 py-0.5 rounded-full {bg} text-zinc-900')
