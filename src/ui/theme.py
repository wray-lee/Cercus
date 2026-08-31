"""Dark theme + CSS variable overrides matching web mirror palette."""
from nicegui import ui

_THEME_CSS = '''
    :root {
        --bg: #0A0A0B;
        --card: rgba(20, 20, 22, 0.7);
        --card-solid: #141416;
        --card2: #0E0E11;
        --border: #262629;
        --border-glow: linear-gradient(135deg, #22D3EE 0%, #A3E635 100%);
        --text: #E5E7EB;
        --muted: #71717A;
        --accent: #22D3EE;
        --lime: #A3E635;
        --warn: #FB923C;
        --err: #F87171;
    }
    body {
        background: radial-gradient(circle at top left, #0F0F11 0%, #0A0A0B 100%) !important;
        overflow: hidden;
    }
    .nicegui-content {
        background: transparent !important;
        max-width: 100% !important;
        padding: 0 !important;
    }
    .q-card {
        background: var(--card) !important;
        backdrop-filter: blur(12px);
        border: 1px solid var(--border);
        border-radius: 10px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05);
    }
    .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }

    /* Compact form inputs with glow on focus */
    .q-field--dense .q-field__control { min-height: 36px !important; }
    .q-field--dense .q-field__label { font-size: 11px; }
    .q-field--dense input { font-size: 12px; }
    .q-field--focused .q-field__control {
        box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.3) !important;
    }

    /* Buttons with gradient hover */
    .q-btn:hover {
        box-shadow: 0 2px 8px rgba(34, 211, 238, 0.3);
        transition: all 0.2s ease;
    }

    /* Custom scrollbar */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: var(--card2); border-radius: 4px; }
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #22D3EE 0%, #A3E635 100%);
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover { opacity: 0.8; }

    /* Drag region cursor */
    .drag-handle { cursor: move; user-select: none; }

    /* Table zebra stripes */
    .q-table tbody tr:nth-child(even) {
        background: rgba(14, 14, 17, 0.4);
    }

    /* Status dot indicator */
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 6px;
        box-shadow: 0 0 8px currentColor;
    }
'''


def apply_theme():
    """Call inside each @ui.page function (or use app.on_connect).

    NiceGUI script mode detects global-scope UI calls and raises RuntimeError
    if ui.page is also used, so theme must be applied per-page, not globally.
    """
    ui.dark_mode(True)
    ui.add_css(_THEME_CSS)
