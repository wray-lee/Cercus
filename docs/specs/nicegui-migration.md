# NiceGUI Dashboard Migration Spec

## Status: APPROVED

## Destination

Replace the legacy desktop dashboard + standalone HTML web mirror with a
unified NiceGUI application. The native window (`pywebview`) serves as the
experiment control panel; a browser-accessible `/monitor` route provides
read-only observation. One codebase, one process, one server.

## Decisions

| # | Decision | Choice |
|---|----------|--------|
| Q1 | Migration strategy | One-shot rewrite on `feature/nicegui-dashboard`, orchestrator review before merge |
| Q2 | Responsibility split | 3-layer: `ExperimentController` → `AppState` → NiceGUI pages/components |
| Q3 | Worker communication | `app.timer(0.033, poll_fn)` — global NiceGUI timer, equivalent to `root.after(16)` |
| Q4 | WebBridge / web_telemetry | Delete both — NiceGUI is the web server |
| Q5 | Trajectory canvas | Custom Vue component wrapping existing Canvas JS |
| Q6 | /dashboard access control | One-time `secrets.token_urlsafe(32)`, native window opens `/dashboard?token=<T>`, server rejects mismatched token |
| Q7 | Dashboard layout | Two-column: left = config + control, right = live status + visualizations |
| Q8 | Calibration panel | Matrix display only — load from json + Apply. No axis calibration UI (external tool). Collapsible. |
| Q9 | /monitor permission isolation | Route-level — /monitor Python code contains no control buttons, no start/stop endpoint |
| Q10 | File structure | Layer-based split (see below) |
| Q11 | Branch | `feature/nicegui-dashboard`, merge to main, tag v2.0.0 |
| Q12 | Theme | `ui.dark_mode(True)` + CSS variable overrides matching web mirror palette |
| Q13 | Old files | Delete on feature branch (v1.0.0 branch/tag preserves history) |
| Q14 | Twin preview canvas | Custom Vue component wrapping existing `drawCmd` JS |

## Architecture

### Layer Diagram

```
┌─────────────────────────────────────────────────┐
│  NiceGUI Server (uvicorn, single process)        │
│                                                   │
│  ┌──────────────┐  ┌───────────────┐              │
│  │ /dashboard   │  │ /monitor      │   Pages      │
│  │ (native win) │  │ (browser)     │              │
│  │ + controls   │  │ read-only     │              │
│  └──────┬───────┘  └──────┬────────┘              │
│         │                 │                        │
│  ┌──────┴─────────────────┴────────┐               │
│  │  Shared Components              │               │
│  │  config_panel, trajectory,      │               │
│  │  twin_preview, verdict_table,   │               │
│  │  hw_status, calibration         │               │
│  └──────────────┬──────────────────┘               │
│                 │                                   │
│  ┌──────────────┴──────────────────┐               │
│  │  AppState (reactive)            │               │
│  │  telemetry, config, verdicts,   │               │
│  │  trajectory, calibration        │               │
│  └──────────────┬──────────────────┘               │
│                 │                                   │
│  ┌──────────────┴──────────────────┐               │
│  │  ExperimentController           │               │
│  │  worker lifecycle, mp.Queue,    │               │
│  │  config build, calibration mgmt │               │
│  └──────────────┬──────────────────┘               │
│                 │                                   │
└─────────────────┼───────────────────────────────────┘
                  │ mp.Queue (cross-process)
         ┌────────┴────────┐
         │ stimulus_worker  │
         │ (separate proc)  │
         └─────────────────┘
```

### File Structure

```
src/ui/
├── app.py                  # NiceGUI entry: ui.run(native=True), token gen, routing
├── controller.py           # ExperimentController — worker lifecycle, config build
├── state.py                # AppState — reactive state, telemetry consumer
├── pages/
│   ├── dashboard.py        # /dashboard page (token-gated, has controls)
│   └── monitor.py          # /monitor page (read-only)
├── components/
│   ├── config_panel.py     # Dynamic param form from paradigm schema
│   ├── calibration.py      # Matrix display (load json + apply), collapsible
│   ├── trajectory.py       # Trajectory canvas (Vue component wrapper)
│   ├── trajectory.js       # Trajectory canvas (JS rendering: bbox, decimation, arrow)
│   ├── twin_preview.py     # Twin stimulus preview (Vue component wrapper)
│   ├── twin_preview.js     # Twin preview (drawCmd replay)
│   ├── verdict_table.py    # Verdict table + summary
│   └── hw_status.py        # Hardware state display
└── theme.py                # Dark mode + CSS variable overrides
```

### Deleted Files

- `src/ui/dashboard.py` (CTk, replaced by pages/ + components/ + controller + state)
- `src/ui/static/index.html` (standalone web mirror, replaced by /monitor)
- `src/ui/legacy web bridge` (state serialization layer, replaced by AppState)
- `src/core/legacy web telemetry` (separate legacy HTTP server process, replaced by NiceGUI server)

## Detailed Design

### 1. ExperimentController (`controller.py`)

Pure Python, no NiceGUI dependency. Extracted from MasterDashboard:

- `start_experiment(config: dict)` → spawn worker process, create queues
- `stop_experiment()` → send POISON_PILL
- `load_calibration_matrix(path?)` → load 3×3 from json
- `save_calibration_matrix(matrix, path?)` → write to json
- `poll_telemetry()` → drain queue, return structured events
- `build_config(form: dict) -> dict` — static, extracted from `_build_config()`
- `cleanup_worker()`
- Properties: `worker_alive`, `calib_active`, `terminal_status`, `terminal_error`

Does NOT hold UI state (no widgets, no labels, no StringVars).

### 2. AppState (`state.py`)

Reactive state object consumed by both pages. Updated by `app.timer` polling controller.

```python
class AppState:
    # Live telemetry
    phase: str = "IDLE"
    ui_color: str = "gray"
    session_num: int | str = "—"
    trial_idx: int | str = "—"
    total_trials: int | str = "—"
    hardware_metrics: dict = {}
    status_text: str = "Ready"
    status_color: str = "gray"
    worker_status: str = "idle"  # running|worker_done|worker_abort|worker_error|idle
    worker_error: str = ""

    # Trajectory
    trail_points: list[tuple] = []
    trail_bbox: tuple | None = None  # (min_x, max_x, min_y, max_y) — monotonic
    trail_angle: float = 0.0
    kinematic: dict = {}  # k_angle, k_turn_speed, k_disp

    # Twin preview
    ui_twin: dict | None = None

    # Calibration (matrix-only — no live axis process per Q8)
    calib_matrix: list[list[float]] = []  # loaded from json

    # Verdicts
    verdict_history: list[dict] = []
    verdict_counts: dict = {}  # {escape: N, startle: N, no_response: N}

    # Config (for monitor display)
    config_snapshot: dict = {}

    # Controls state (managed by UI callbacks, not polled)
    # can_start / can_stop omitted — buttons enabled/disabled directly
    can_stop: bool = False
```

### 3. Polling Loop

```python
# In app.py — SINGLE global timer, not per-client
controller = ExperimentController()
state = AppState()

def _global_poll():
    events = controller.poll_telemetry()
    state.apply(events)
    if state.worker_died:
        controller.cleanup_worker()

app.on_startup(lambda: ui.timer(0.033, _global_poll))  # 30 Hz
# Per-client timers only read state — they never call poll_telemetry()
    state.apply(events)  # updates all reactive fields
    # NiceGUI auto-updates bound UI elements

app.timer(0.033, poll)  # 30 Hz, same as current root.after(16)
```

### 4. /dashboard Page

Token-gated. Two-column layout:

**Left column (fixed ~350px):**
- Subject ID + New button
- Paradigm selector → dynamic param form (`config_panel.py`)
- Execution Mode + session controls
- Start / Stop buttons
- Calibration collapsible (`calibration.py`)

**Right column (flex):**
- Phase pill + session/trial progress
- Status bar (worker badge, status label)
- Twin preview (`twin_preview.py`)
- Trajectory canvas (`trajectory.py`) + kinematic readouts
- Hardware state cards
- Verdict table (`verdict_table.py`) + summary

### 5. /monitor Page

No token required. Same right column components, same AppState binding.
Additionally shows config snapshot (paradigm, subject, session) as read-only cards.
No start/stop buttons, no config editing, no calibration.

### 6. /dashboard Access Control

```python
import secrets
DASHBOARD_TOKEN = secrets.token_urlsafe(32)

@ui.page('/dashboard')
def dashboard_page(token: str = ''):
    if token != DASHBOARD_TOKEN:
        ui.label('Access denied').classes('text-red-500 text-2xl')
        return
    build_dashboard(state, controller)

ui.run(
    native=True,
    host='0.0.0.0',
    port=8000,
    title='Cercus · Experiment Dashboard',
    window_size=(1400, 900),
)
# native window opens /dashboard?token=<DASHBOARD_TOKEN>
```

### 7. Custom Vue Components

**trajectory.js** — ported from `index.html:renderTraj`:
- Receives `{trail_points, min_x, max_x, min_y, max_y, angle}` via props
- Monotonic bbox is handled server-side (AppState), JS just renders
- Dirty guard, decimation with tail preservation, NaN guard, arrow rendering
- `run_method('updateTrajectory', data)` from Python

**twin_preview.js** — ported from `index.html:renderTwin`:
- Receives draw command list via props
- Replays `drawCmd` on HTML5 Canvas
- `run_method('updateTwin', cmds)` from Python

### 8. Config Panel Dynamic Form

Extracted from `_do_refresh` / `refresh_dynamic_parameters`:

```python
def build_param_form(schema: dict, container, values: dict) -> dict[str, Element]:
    widgets = {}
    for key, meta in schema.items():
        match meta.get('type'):
            case 'info':    ui.label(meta['label']).classes('text-zinc-500')
            case 'choice':  widgets[key] = ui.select(meta['choices'], value=...)
            case 'bool':    widgets[key] = ui.switch(meta['label'], value=...)
            case 'filepath': ...  # ui.input + file picker button
            case 'int'|'float'|'string'|_: widgets[key] = ui.input(meta['label'], value=...)
    return widgets
```

Rebuilt on paradigm change. Validation via NiceGUI's `validation=` kwarg.

### 9. Theme (`theme.py`)

```python
def apply_theme():
    ui.dark_mode(True)
    ui.add_css('''
        :root {
            --bg: #0A0A0B;
            --card: #141416;
            --border: #262629;
            --text: #E5E7EB;
            --muted: #71717A;
            --accent: #22D3EE;
            --lime: #A3E635;
        }
        body { background: var(--bg) !important; }
        .nicegui-content { background: var(--bg) !important; }
    ''')
```

## Migration Mapping

| Current (CTk) | New (NiceGUI) |
|--------------|---------------|
| `MasterDashboard.__init__` (507-571) | `controller.py` + `state.py` + `app.py` |
| `_create_widgets` (766-1143) | `pages/dashboard.py` + `components/*` |
| `refresh_dynamic_parameters` / `_do_refresh` (1162-1343) | `components/config_panel.py` |
| `_build_config` (1399-1496) | `controller.build_config()` |
| `_poll_telemetry` (1714-1834) | `app.timer` + `controller.poll_telemetry()` + `state.apply()` |
| `_update_telemetry_ui` / `_draw_twin` | `state.apply()` → NiceGUI binding |
| `_update_trajectory` / `_draw_trajectory` (1926-2068) | `state.apply()` → `trajectory.py` → `trajectory.js` |
| `_append_verdict` / verdict table (2086-2130) | `state.apply()` → `verdict_table.py` |
| `start_experiment` / `stop_experiment` (1677-1710) | `controller.start/stop_experiment()` |
| Calibration callbacks (1574-1673) | `controller.*_calibration()` + `components/calibration.py` |
| `_start_web_server` / `_push_web_state` (675-760) | Deleted — NiceGUI IS the server |
| `legacy web bridge` | Deleted — AppState replaces |
| `legacy web telemetry` | Deleted — NiceGUI server replaces |
| `static/index.html` | Deleted — /monitor page replaces |
| `CalibrationPanel` (84-484) | `components/calibration.py` (UI) + `controller.py` (matrix math) |

## Constraints

1. **stimulus_worker.py is untouched** — no changes to the worker process, paradigm, or kinematics
2. **mp.Queue contract unchanged** — same telemetry dict format, same POISON_PILL shutdown
3. **PARADIGM_REGISTRY and get_parameter_schema() unchanged** — same schema format drives the new form
4. **Data output format unchanged** — experiment data files are written by the worker, not the UI
5. **Calibration matrix math unchanged** — extracted verbatim from CalibrationPanel
6. **`native=True` requires `pip install nicegui[native]`** — adds pywebview dependency
7. **Single-worker uvicorn** — NiceGUI native mode requires `workers=1`
8. **Native window close = server shutdown** — expected behavior, same as current CTk `WM_DELETE_WINDOW`

## Dependencies

New:
- `nicegui[native]` (>= 3.16)

Removed:
- `customtkinter` (no longer needed)
- Direct `fastapi` / `uvicorn` imports in `legacy web telemetry` (NiceGUI bundles these)

## Testing

- `tests/test_verdict.py` — unchanged (tests `BaseParadigm.classify_response`, no UI)
- `tests/test_trajectory.py` — unchanged (tests bbox logic extracted to pure function)
- New: `tests/test_controller.py` — ExperimentController unit tests (config build, queue polling)
- New: `tests/test_state.py` — AppState.apply() event processing
- Manual: native window launch, /monitor browser access, token rejection, start/stop experiment
