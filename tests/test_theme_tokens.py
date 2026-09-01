"""Tests for theme design tokens.

Seam: theme._THEME_CSS token definitions + component token references.

Guards the START/STOP button color contract: colors live in theme.py as
CSS custom properties (per theme.py's no-hardcoded-hex rule), and the
components must apply them with !important — without it Quasar's
.bg-primary rule wins and both buttons render default blue.
"""
import inspect

from src.ui.pages import dashboard
from src.ui.theme import _THEME_CSS


def test_action_button_tokens_defined() -> None:
    """theme.py defines the saturated START/STOP action colors."""
    assert '--btn-start:' in _THEME_CSS
    assert '--btn-stop:' in _THEME_CSS


def test_action_buttons_reference_tokens_with_important() -> None:
    """dashboard.py references the tokens and forces them over Quasar."""
    source = inspect.getsource(dashboard.build_dashboard)
    assert 'var(--btn-start) !important' in source, (
        'START button must apply var(--btn-start) with !important; '
        'plain background/var() loses to Quasar .bg-primary'
    )
    assert 'var(--btn-stop) !important' in source, (
        'STOP button must apply var(--btn-stop) with !important'
    )
    assert '#22A55B' not in source and '#E03C31' not in source, (
        'button colors must come from theme.py tokens, not hardcoded hex'
    )
