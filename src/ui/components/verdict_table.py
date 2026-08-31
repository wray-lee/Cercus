"""Verdict table + summary — NiceGUI component."""
from nicegui import ui


COLOR_MAP = {
    'escape': 'text-red-400',
    'startle': 'text-amber-400',
    'no_response': 'text-zinc-500',
}


def verdict_table(state) -> ui.element:
    """Create verdict table card bound to AppState."""
    with ui.card().classes('w-full') as card:
        with ui.row().classes('items-center gap-2 mb-1'):
            ui.label('Verdicts').classes('text-sm font-semibold text-zinc-300')
            summary_label = ui.label('').classes('text-xs text-zinc-500 mono')

        columns = [
            {'name': 'trial', 'label': '#', 'field': 'trial', 'align': 'center', 'style': 'width: 40px'},
            {'name': 'side', 'label': 'Side', 'field': 'side', 'align': 'center'},
            {'name': 'response', 'label': 'Response', 'field': 'response', 'align': 'center'},
            {'name': 'disp', 'label': 'Disp(mm)', 'field': 'disp', 'align': 'right'},
            {'name': 'angle', 'label': 'Angle(°)', 'field': 'angle', 'align': 'right'},
        ]
        table = ui.table(columns=columns, rows=[], row_key='trial').classes('w-full')
        table.style('max-height: 120px; overflow-y: auto')

    def refresh():
        rows = []
        for v in state.verdict_history:
            rows.append({
                'trial': v.get('trial_idx', '—'),
                'side': v.get('side', '—'),
                'response': v.get('response', '—'),
                'disp': round(v.get('cum_disp', 0), 2),
                'angle': round(v.get('cum_dz', 0), 2),
            })
        table.rows = rows
        table.update()

        c = state.verdict_counts
        parts = []
        if c.get('escape'): parts.append(f"{c['escape']} escape")
        if c.get('startle'): parts.append(f"{c['startle']} startle")
        if c.get('no_response'): parts.append(f"{c['no_response']} no_resp")
        summary_label.text = ' · '.join(parts)

    card._verdict_refresh = refresh
    return card
