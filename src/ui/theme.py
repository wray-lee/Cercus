"""Dark theme + CSS variable overrides matching web mirror palette."""
from nicegui import ui

_THEME_CSS = '''
    :root {
        --bg: #0B1120;
        --bg-gradient-start: #0F172A;
        --bg-gradient-end: #0B1120;
        --card: rgba(15, 23, 42, 0.6);
        --card-solid: #1E293B;
        --card2: #0F172A;
        --border: #334155;
        --border-glow: linear-gradient(135deg, #3B82F6 0%, #06B6D4 100%);
        --text: #F1F5F9;
        --text-secondary: #94A3B8;
        --muted: #64748B;
        --accent: #3B82F6;
        --accent-bright: #60A5FA;
        --cyan: #06B6D4;
        --lime: #84CC16;
        --warn: #F59E0B;
        --err: #EF4444;
    }
    body {
        background: linear-gradient(135deg, var(--bg-gradient-start) 0%, var(--bg-gradient-end) 100%) !important;
        overflow: hidden;
    }
    .nicegui-content {
        background: transparent !important;
        max-width: 100% !important;
        padding: 0 !important;
    }
    .q-card {
        background: var(--card) !important;
        backdrop-filter: blur(16px);
        border: 1px solid var(--border);
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.4), inset 0 1px 0 rgba(59,130,246,0.1);
    }
    .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }

    /* Enhanced form inputs with larger labels */
    .q-field--dense .q-field__control {
        min-height: 40px !important;
        background: rgba(15, 23, 42, 0.5);
        border-radius: 8px;
    }
    .q-field--dense .q-field__label {
        font-size: 12px !important;
        font-weight: 500 !important;
        color: var(--text-secondary) !important;
    }
    .q-field--dense input, .q-field--dense .q-field__native {
        font-size: 13px !important;
        color: var(--text) !important;
    }
    .q-field--focused .q-field__control {
        background: rgba(59, 130, 246, 0.1) !important;
        border-color: var(--accent-bright) !important;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2) !important;
    }
    .q-field--outlined .q-field__control:before {
        border-color: var(--border) !important;
    }

    /* Buttons with blue gradient */
    .q-btn {
        text-transform: none;
        font-weight: 600;
        border-radius: 8px;
    }
    .q-btn:hover {
        box-shadow: 0 4px 16px rgba(59, 130, 246, 0.4);
        transition: all 0.2s ease;
        transform: translateY(-1px);
    }

    /* Custom scrollbar with blue gradient */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track {
        background: var(--card2);
        border-radius: 5px;
    }
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #3B82F6 0%, #06B6D4 100%);
        border-radius: 5px;
        border: 2px solid var(--card2);
    }
    ::-webkit-scrollbar-thumb:hover { opacity: 0.8; }

    /* Drag region cursor */
    .drag-handle { cursor: move; user-select: none; }

    /* Table zebra stripes */
    .q-table tbody tr:nth-child(even) {
        background: rgba(15, 23, 42, 0.3);
    }
    .q-table thead th {
        font-weight: 600 !important;
        color: var(--text-secondary) !important;
    }

    /* Status dot indicator with blue glow */
    .status-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 8px;
        box-shadow: 0 0 12px currentColor;
        animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }

    /* Card headers */
    .glass-card {
        background: rgba(30, 41, 59, 0.5) !important;
    }
'''


def apply_theme():
    """Call inside each @ui.page function (or use app.on_connect).

    NiceGUI script mode detects global-scope UI calls and raises RuntimeError
    if ui.page is also used, so theme must be applied per-page, not globally.
    """
    ui.dark_mode(True)
    ui.add_css(_THEME_CSS)
