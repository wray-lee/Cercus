"""Dark theme + CSS variable overrides matching web mirror palette."""
from nicegui import ui

_THEME_CSS = '''
    :root {
        --bg: #0A0A0B;
        --card: #141416;
        --card2: #0E0E11;
        --border: #262629;
        --border2: #1f1f22;
        --text: #E5E7EB;
        --muted: #71717A;
        --accent: #22D3EE;
        --lime: #A3E635;
        --warn: #FB923C;
        --err: #F87171;
    }
    body { background: var(--bg) !important; }
    .nicegui-content { background: var(--bg) !important; max-width: 100% !important; }
    .q-card { background: var(--card) !important; border: 1px solid var(--border); }
    .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }
'''


def apply_theme():
    """Call inside each @ui.page function (or use app.on_connect).

    NiceGUI script mode detects global-scope UI calls and raises RuntimeError
    if ui.page is also used, so theme must be applied per-page, not globally.
    """
    ui.dark_mode(True)
    ui.add_css(_THEME_CSS)
