"""Cercus visual system — \"Warm Instrument\" design tokens.

All colors, typography, and component styles are defined here as CSS
custom properties.  Components reference these tokens — no hardcoded
hex values outside this file.
"""
from nicegui import ui

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=DM+Sans:wght@400;500;600;700&'
    'family=IBM+Plex+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
)

_THEME_CSS = '''
    /* ── Design tokens ── */
    :root {
        --bg:              #111110;
        --surface:         #1A1A18;
        --surface-raised:  #232320;
        --border:          #2E2E2A;
        --text:            #E8E6E1;
        --text-muted:      #807D75;
        --accent:          #6EDBA1;
        --ok:              #8DB954;
        --warn:            #D4883A;
        --err:             #C75449;
        /* Primary action buttons — saturated for unambiguous START/STOP
           contrast (v1.0.0 parity). Must be applied with !important to
           override Quasar's .bg-primary. */
        --btn-start:       #22A55B;
        --btn-stop:        #E03C31;
    }

    /* ── Global ── */
    html, body {
        font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
    }
    body {
        background: var(--bg) !important;
        background-image:
            radial-gradient(1200px 600px at 85% -10%, rgba(110,219,161,0.04), transparent 60%),
            radial-gradient(1000px 500px at 10% 110%, rgba(210,170,100,0.03), transparent 60%);
    }
    .nicegui-content {
        background: transparent !important;
        max-width: 100% !important;
        padding: 0 !important;
    }

    /* ── Typography ── */
    .mono {
        font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace;
        font-variant-numeric: tabular-nums;
    }
    .sec-title {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-muted);
    }

    /* ── Cards ── */
    .q-card {
        background: var(--surface) !important;
        border: 1px solid var(--border);
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.35);
        backdrop-filter: none !important;
    }

    /* ── Form inputs ── */
    .q-field--dense .q-field__control {
        min-height: 36px !important;
        background: var(--surface-raised);
        border-radius: 6px;
    }
    .q-field--dense .q-field__label {
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 11.5px !important;
        font-weight: 500 !important;
        color: var(--text-muted) !important;
    }
    .q-field--dense input,
    .q-field--dense .q-field__native {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 12px !important;
        color: var(--text) !important;
    }
    .q-field--outlined .q-field__control:before {
        border-color: var(--border) !important;
    }
    .q-field--focused .q-field__control {
        background: rgba(110, 219, 161, 0.06) !important;
        border-color: var(--accent) !important;
    }
    .q-field--focused .q-field__control:before {
        border-color: var(--accent) !important;
    }
    .q-field--focused .q-field__control:after {
        border-color: var(--accent) !important;
        border-width: 1px !important;
        box-shadow: 0 0 0 2px rgba(110, 219, 161, 0.12);
    }

    /* ── Buttons ── */
    .q-btn {
        text-transform: none;
        font-family: 'DM Sans', system-ui, sans-serif;
        font-weight: 600;
        border-radius: 6px;
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: var(--bg); }
    ::-webkit-scrollbar-thumb {
        background: var(--surface-raised);
        border-radius: 4px;
        border: 2px solid var(--bg);
    }
    ::-webkit-scrollbar-thumb:hover { background: var(--border); }

    /* ── Table ── */
    .q-table tbody tr:nth-child(even) {
        background: rgba(35, 35, 32, 0.5);
    }
    .q-table thead th {
        font-family: 'DM Sans', system-ui, sans-serif;
        font-weight: 600 !important;
        font-size: 10px !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--text-muted) !important;
    }

    /* ── Drag region ── */
    .drag-handle { cursor: move; user-select: none; }

    /* ── Status dot (signature element) ── */
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 6px;
        flex-shrink: 0;
    }
    .status-dot.active {
        box-shadow: 0 0 8px currentColor;
        animation: dot-pulse 2s ease-in-out infinite;
    }
    @keyframes dot-pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }

    /* ── Nested cells (hw metrics, calibration matrix, config grid) ── */
    .cell {
        background: var(--surface-raised);
        border: 1px solid var(--border);
        border-radius: 4px;
    }

    /* ── Status strip ── */
    .status-strip {
        background: var(--surface-raised);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 6px 12px;
    }

    /* ── Chip/pill badges ── */
    .chip {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 9.5px;
        font-weight: 500;
        letter-spacing: 0.02em;
        padding: 1px 8px;
        border-radius: 999px;
        white-space: nowrap;
    }

    /* ── Data change flash animation (v1.0.0 FlashRow equivalent) ── */
    .flash-row {
        animation: flash-highlight 0.55s ease;
    }
    @keyframes flash-highlight {
        0%   { background-color: rgba(110, 219, 161, 0.18); }
        100% { background-color: transparent; }
    }

    /* ── Phase glow animation (v1.0.0 GlowPhase equivalent) ── */
    .phase-glow {
        animation: phase-glow-anim 1.6s ease-in-out infinite;
    }
    @keyframes phase-glow-anim {
        0%, 100% { text-shadow: 0 0 6px currentColor; }
        50%      { text-shadow: 0 0 14px currentColor; }
    }
'''


def apply_theme() -> None:
    """Call inside each @ui.page function.

    NiceGUI script mode detects global-scope UI calls and raises RuntimeError
    if ui.page is also used, so theme must be applied per-page, not globally.
    """
    ui.dark_mode(True)
    ui.add_head_html(_FONTS)
    ui.add_css(_THEME_CSS)
