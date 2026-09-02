# Cercus

**Cercus** is a multiprocess, closed-loop stimulus control framework for high-temporal-precision behavioral and neuroscience experiments. Built on a Master-Worker architecture, it physically decouples UI scheduling, visual rendering, hardware telemetry, and data persistence.

---

# Part I — Researcher User Guide

## 1. Overview

Cercus enforces strict unidirectional data flow and functional isolation between four subsystems:

- **Dashboard** (`src/ui/app.py`): A NiceGUI-based desktop application (native window via pywebview) for parameter configuration, dynamic form generation, and real-time status monitoring. A read-only **web monitor** (`/monitor`) is accessible from any browser on the LAN.
- **Pure Logic Core** (`src/models/paradigm.py`): A mathematical modeling layer that processes time deltas and hardware feedback to output standardized rendering instruction streams.
- **Stateless Renderer** (`src/core/render.py`): Executes basic geometric drawing instructions (`circle`, `rect`, `element_array`) without maintaining state.
- **Asynchronous Hardware Daemon** (`src/core/hardware.py`): Handles high-frequency sensor data acquisition and TTL trigger signal dispatch.
- **Dual-Track Logger** (`src/core/logger.py`): Separates high-frequency kinematics telemetry from low-frequency experimental state transitions.

### Execution Modes

| Mode          | Behavior                                                                                                                                                                   |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Auto**      | Continuously executes the entire session automatically based on randomized ITI/ISI intervals.                                                                              |
| **Manual**    | After the ITI, the renderer safely suspends and waits for external input (`Space` bar) to trigger a single trial.                                                          |
| **Kinematic** | The trial starts automatically once a kinematic trigger condition is met (e.g., movement distance, angle, or speed threshold). Thresholds are configured in the dashboard. |

## 2. Quick Start

Install dependencies in an isolated virtual environment (e.g., Conda):

```bash
pip install -r requirements.txt
```

Launch the dashboard:

```bash
python main.py
```

The native dashboard window opens automatically. A read-only monitor is available at `http://<your-ip>:8000/monitor` from any browser on the LAN.

## 3. Built-in Paradigms

The following paradigms are built-in and can be dynamically loaded via the dashboard dropdown:

| Paradigm           | Description                                                                                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Looming**        | Multi-modal looming stimulus with visual + wind field. Includes pure visual and pure wind baselines, plus 7 calibrated visuo-tactile conditions with gradient wind triggers from TTC -373ms to +200ms. |
| **ClassicLooming** | Pure visual parameterized looming model. Supports dynamic configuration of l/v ratio, initial/final degrees, and left/right presentation logic.                                                        |
| **OpticFlow**      | Vectorized dot-motion model. Configurable speed, density, coherence, and direction.                                                                                                                    |
| **MovementTrace**  | Lissajous trajectory tracking. Configurable X/Y frequency, amplitude, and trail length.                                                                                                                |
| **Grating**        | Sinusoidal grating stimulus. Supports static and drifting modes with configurable spatial frequency, temporal frequency, orientation, and contrast.                                                    |
| **SingleLooming**  | Single-screen centered looming stimulus. Same multi-modal conditions as Looming but designed for single-display setups.                                                                                |
| **Blank**          | No stimulus — hardware tracking only. Useful for baseline recordings.                                                                                                                                  |
| **Wind**           | Pure wind stimulus without visual rendering. Configurable onset delay and fixed post-wind recording.                                                                                                    |

## 4. Physical Calibration

Calibration is performed using an external tool that generates a `calibration_cfg.json` file containing the 3×3 decoupling matrix.

The dashboard provides a **Calibration Matrix** panel (collapsible) that:
1. Loads the matrix from `calibration_cfg.json` on startup.
2. Displays the 3×3 matrix values.
3. Allows reloading and applying the matrix, which is injected into the hardware daemon for subsequent experiments.

## 5. Modifying Default Parameters

You can permanently change default values by editing source files directly. This eliminates the need to re-enter the same parameters every time you launch the dashboard.

### Change the default-loaded paradigm

Open `src/models/paradigm.py` and scroll to the `PARADIGM_REGISTRY` dictionary at the bottom of the file:

```python
PARADIGM_REGISTRY: Dict[str, type] = {
    "Looming": LoomingParadigm,
    "ClassicLooming": ClassicLoomingParadigm,
    "OpticFlow": OpticFlowParadigm,
    "MovementTrace": MovementTraceParadigm,
    "Blank": BlankParadigm,
    "Grating": GratingParadigm,
    "SingleLooming": SingleLoomingParadigm,
    "Wind": WindParadigm,
}
```

The dashboard defaults to the **first key** in this dictionary. Move your most-used paradigm to the first position.

### Change global default parameters (Subject ID, Resolution, ITI/ISI, etc.)

Default values are set in `src/ui/components/config_panel.py`. Edit the `value=` argument of the corresponding `ui.input()` or `ui.number()` widget.

### Change paradigm-specific parameters (contrast, spatial frequency, speed, etc.)

Open `src/models/paradigm.py` and find the target paradigm class. Inside that class, locate the `get_parameter_schema(cls)` method. Each parameter is a dictionary entry — change the `"default"` value.

## 6. Data Output

Dual-track record files are automatically generated in the `data/` directory, aligned via `global_trial_id` and timestamps:

1. **`{Subject}_session_{n}_events.csv`** — Low-frequency experimental state events. Columns: `event_name`, `timestamp`, `session_num`, `trial_in_session`, `global_trial_id`, `details` (JSON).
2. **`{Subject}_session_{n}_kinematics.csv`** — High-frequency closed-loop telemetry. Columns: `sys_time`, `ard_time`, `dx`, `dy`, `dz`, `stim_state`, `global_trial_id`.

Both files share `global_trial_id` as the join key for cross-referencing trial-level events with frame-level kinematics.

## 7. Web Monitor

The dashboard runs an integrated web server (NiceGUI + uvicorn) accessible from any browser on the LAN.

### Access

- The monitor URL is printed at startup, e.g. `Monitor available at: http://<host>:8000/monitor`.
- The server binds `0.0.0.0:8000`.
- The dashboard native window is token-gated — browser access to `/dashboard` is denied.

### What it shows

- **Live status**: phase badge, session + trial progress, worker status, and status line.
- **Stimulus twin**: a canvas replaying the stimulus render instructions.
- **Trajectory**: a canvas plotting the recent path with the current heading arrow, plus θ/ω/D kinematics.
- **Calibration matrix**: the current 3×3 decoupling matrix.
- **Configuration**: all parameters, including dynamic paradigm params.
- **Verdict table**: post-trial behavioral classification results.

### Architecture

The dashboard and monitor share a single NiceGUI server process. A global `app.timer` at 30 Hz polls the worker's `mp.Queue` and updates a shared `AppState` object. Per-client timers in each page read from this shared state to update their widgets — no queue races.

### Notes

- The browser and the experiment PC must be on the same network.
- The monitor is strictly read-only — no start/stop controls are exposed.
- Closing the native dashboard window shuts down the server.

---

# Part II — Developer Guide

## 1. Adding New Paradigms

New experimental paradigms can be added without modifying the rendering engine or control flow code. All development is confined to `src/models/paradigm.py`.

### Step 1: Inherit Base Class

Create a new class inheriting from `BaseParadigm`:

```python
from src.models.paradigm import BaseParadigm

class MyParadigm(BaseParadigm):
    ...
```

### Step 2: Define UI Mapping Interfaces

- **`get_available_patterns(cls)`**: Return a list of supported pattern names (shown in the dashboard Pattern dropdown).
- **`get_parameter_schema(cls)`**: Declare the dynamic UI parameter dictionary. The framework reads the `type` field to auto-generate dashboard form widgets. Supported types: `int`, `float`, `str`, `choice`, `bool`, `info`, `filepath`.

### Step 3: Implement Core Lifecycle

- **`generate_trials(self, pattern_key)`**: Construct and return the trial contexts (`List[dict]`) for the session based on the selected pattern.
- **`prepare_trial(self, trial_context)`**: Return hardware initialization serial commands before a trial starts (or an empty string `""`).
- **`get_idle_frame(self, hw_telemetry)`**: Return steady-state rendering instructions for ITI/ISI phases as `(cmds, telemetry_dict)`.
- **`process_frame(self, elapsed_time, trial_context, hw_telemetry)`**: The frame-level closed-loop calculation core. Return `(is_done, cmds, telemetry_dict)` based on the timestamp and hardware telemetry.

### Step 4: Standardized Rendering Instructions

The `cmds` list returned by lifecycle methods must use dictionaries with these supported `type` values:

| Type            | Key Parameters                                                  |
| --------------- | --------------------------------------------------------------- |
| `circle`        | `radius`, `pos`, `fillColor`, `lineColor`, `lineWidth`, `edges` |
| `rect`          | `width`, `height`, `pos`, `fillColor`, `lineColor`, `lineWidth` |
| `element_array` | `n_elements`, `xys`, `sizes`, `colors`, `opacities`             |

Color values use PsychoPy RGB convention: `-1` = black, `0` = mid-gray, `+1` = white.

#### Sync Block Protocol (Photodiode Markers)

> **Architecture Note**: The legacy `ScreenEnvironment` class has been deprecated. The low-level `CoreRenderer` (`src/core/render.py`) maintains **zero awareness** of photodiode markers or sync blocks — it blindly draws whatever `cmds` it receives. All sync logic is fully owned by the paradigm layer and expressed entirely through the returned instruction packets.

Every paradigm is responsible for appending the correct number of photodiode sync blocks to its `cmds` list. The framework provides `BaseParadigm._build_sync_markers(is_active, mode)` as a shared utility, but paradigms may implement their own coordinate logic if needed.

### Step 5: Global Registration

Add the new class to the `PARADIGM_REGISTRY` dictionary at the bottom of `src/models/paradigm.py`:

```python
PARADIGM_REGISTRY: Dict[str, type] = {
    ...
    "MyParadigm": MyParadigm,  # <-- register here
}
```

The paradigm will appear in the dashboard dropdown on the next launch.

## 2. UI Architecture

The UI is built on a 3-layer architecture:

```
src/ui/
├── app.py              # NiceGUI entry: ui.run(native=True), token, routing
├── controller.py       # ExperimentController — worker lifecycle, config build
├── state.py            # AppState — reactive state, telemetry consumer
├── theme.py            # Dark mode + CSS variables
├── components/
│   ├── common.py       # Shared helpers (fmt_val, color_pill, etc.)
│   ├── config_panel.py # Dynamic param form from paradigm schema
│   ├── calibration.py  # Matrix display + load/apply
│   ├── trajectory.py/js # Trajectory canvas (HTML5 Canvas)
│   ├── twin_preview.py/js # Stimulus preview canvas
│   ├── verdict_table.py # Post-trial verdict table
│   └── hw_status.py    # Hardware metrics grid
└── pages/
    ├── dashboard.py    # /dashboard (native window, full controls)
    └── monitor.py      # /monitor (browser, read-only)
```

- **ExperimentController**: Pure Python, no UI dependency. Manages worker processes, config building, calibration matrix I/O.
- **AppState**: Reactive state updated by a single global timer. All UI pages read from this shared object.
- **Pages**: Each page applies the theme and creates per-client UI timers that read from AppState.
- **Components**: Reusable UI building blocks shared between dashboard and monitor pages.
