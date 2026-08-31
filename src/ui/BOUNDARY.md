# BOUNDARY.md — Main Controller UI Boundary

## Non-Blocking Callbacks

- ALL NiceGUI page functions, button callbacks, and timer callbacks MUST return immediately (or be async without blocking the event loop).
- Any expensive computation or hardware polling MUST be delegated to:
  - Background threads (`threading.Thread` with `daemon=True`).
  - Worker processes (`mp.Process`).
- Violation: `time.sleep()`, serial port reads, blocking network calls, or long-running loops inside any UI callback.

## Pure Parameter Assembly

- The UI component's SOLE responsibility is:
  1. Collecting user input from form widgets.
  2. Serializing input into a configuration dictionary (`Dict[str, Any]`) via `ExperimentController.build_config()`.
- PROHIBITED in UI thread:
  - Direct instantiation of hardware drivers (`SerialDaemon`, `MockSerialDaemon`).
  - Direct execution of experiment control logic.
  - Direct instantiation of renderers or paradigm objects.
- The configuration dictionary is passed to the worker process; the worker owns all hardware and experiment logic.

## Single Global Timer

- There MUST be exactly ONE `app.timer` that polls the telemetry `mp.Queue` and updates `AppState`.
- Per-client page timers MUST only read from `AppState` — they must never call `controller.poll_telemetry()` directly.
- Violation: multiple clients racing on the same queue, splitting telemetry frames.

## Access Control

- `/dashboard` is token-gated (one-time `secrets.token_urlsafe`). Only the native pywebview window knows the token.
- `/monitor` is read-only. Its Python code MUST NOT contain start/stop buttons or any control endpoints.
