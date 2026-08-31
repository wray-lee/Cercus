"""Verdict table + summary — NiceGUI component."""
from typing import Any
from nicegui import ui

# v1.0.0 response color mapping
_RESPONSE_COLORS = {
    'escape': '#F87171',      # red
    'startle': '#FB923C',     # orange
    'no_response': '#71717A', # gray
}


def verdict_table(state: Any) -> ui.element:
    """Create verdict table card bound to AppState."""
    with ui.card().classes('w-full') as card:
        with ui.row().classes('items-center gap-2 mb-1'):
            ui.icon('checklist').classes('text-[14px]').style('color: var(--text-muted);')
            ui.label('Verdicts').classes('sec-title')
            summary_label = ui.label('').classes('text-[10px] mono').style('color: var(--text-muted);')

        columns = [
            {'name': 'trial', 'label': '#', 'field': 'trial', 'align': 'center', 'style': 'width: 30px; font-size: 10px'},
            {'name': 'side', 'label': 'Side', 'field': 'side', 'align': 'center', 'style': 'font-size: 10px'},
            {'name': 'response', 'label': 'Response', 'field': 'response', 'align': 'center', 'style': 'font-size: 10px'},
            {'name': 'disp', 'label': 'Disp', 'field': 'disp', 'align': 'right', 'style': 'font-size: 10px'},
            {'name': 'angle', 'label': 'Angle', 'field': 'angle', 'align': 'right', 'style': 'font-size: 10px'},
        ]
        table = ui.table(columns=columns, rows=[], row_key='trial').props('dense flat').classes('w-full text-[10px]')
        table.style('max-height: 140px; overflow-y: auto;')

        # Color-coded response chips (v1.0.0 style)
        table.add_slot('body-cell-response', r'''
            <q-td :props="props">
                <q-badge
                    :style="'background: ' + ({'escape':'#F87171','startle':'#FB923C','no_response':'#71717A'}[props.value] || '#71717A') + '; color: #111110; font-size: 9px; font-weight: 700;'"
                    :label="props.value"
                />
            </q-td>
        ''')

    def refresh() -> None:
        rows = []
        for v in state.verdict_history:
            try:
                disp = round(float(v.get('cum_disp') or 0), 2)
            except (ValueError, TypeError):
                disp = 0.0
            try:
                angle = round(float(v.get('cum_dz') or 0), 2)
            except (ValueError, TypeError):
                angle = 0.0
            rows.append({
                'trial': v.get('trial_idx', '—'),
                'side': v.get('side', '—'),
                'response': v.get('response', '—'),
                'disp': disp,
                'angle': angle,
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
