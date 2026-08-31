# ADR 0001: Unified NiceGUI Architecture for Native Control and LAN Monitoring

## Status
Accepted

## Date
2025-02-28

## Context
In Cercus v1.0.0, the user interface was split across two distinct systems:
1. A desktop GUI built with CustomTkinter for local experiment control.
2. A standalone web mirror built with FastAPI, WebSockets, and HTML Canvas for remote LAN observation.

Maintaining two separate UI stacks caused significant architectural liabilities:
- Redundant state tracking and serialization across `MasterDashboard`, `WebBridge`, and `web_telemetry.py`.
- Duplicate UI code for rendering trajectories, visual previews, and status indicators.
- Additional background process overhead and network port management.

## Decision
Migrate the entire user interface layer to NiceGUI (`src/ui/`):
- Run a single-process NiceGUI server hosting both desktop and web endpoints.
- Serve full experiment control on `/dashboard` in a frameless native window (`pywebview`), protected by a one-time cryptographic token (`secrets.token_urlsafe(32)`).
- Serve read-only observation on `/monitor` accessible from any browser on the LAN without control buttons or mutation endpoints.
- Centralize all reactive state in a pure Python `AppState` object (`src/ui/state.py`) updated by a single global timer (`app.timer`) polling the worker telemetry queue.
- Encapsulate worker lifecycle and configuration assembly in `ExperimentController` (`src/ui/controller.py`) with zero UI framework dependencies.

## Consequences
### Positive
- Single unified Python UI codebase with shared reusable components (`config_panel`, `trajectory`, `twin_preview`, `verdict_table`, `hw_status`, `calibration`).
- Elimination of FastAPI/WebSocket bridge processes and state duplication.
- Route-level security isolation between operator controls and LAN observers.

### Negative / Trade-offs
- Native window requires `pywebview` runtime.
- High-frequency telemetry polling must be carefully debounced (30 Hz) to avoid saturating the NiceGUI async event loop.
