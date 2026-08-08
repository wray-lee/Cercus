# Cercus

**Cercus** is a multiprocess, closed-loop stimulus control framework for high-temporal-precision behavioral and neuroscience experiments. Built on a Master-Worker architecture, it physically decouples UI scheduling, visual rendering, hardware telemetry, and data persistence.

---

# Part I — Researcher User Guide

## 1. Overview

Cercus enforces strict unidirectional data flow and functional isolation between four subsystems:

- **Master Dashboard** (`src/ui/dashboard.py`): A non-blocking GUI for parameter configuration, dynamic form generation, and real-time status monitoring. It also spawns a daemon **web mirror** (`src/core/web_telemetry.py`) that broadcasts the dashboard state to any browser on the LAN over WebSocket.
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

## 4. Physical Calibration

The dashboard right-side panel provides a **Physical Calibration** system for decoupling three-axis sensor cross-talk.

### Workflow

1. Click **Enter Calibration** to activate the calibration worker (the stimulus worker will be shut down).
2. Set **Radius (mm)** — the known radius of the calibration sphere.
3. Set **Rotations** — the number of full rotations to record per axis.
4. Click **Calibrate X** (or Y / Z). Roll the sphere strictly in the **positive** direction for that axis. Click **Stop Axis** when done.
5. Repeat for all three axes. The raw vector and target distance for each axis will be displayed.
6. Once all three axes are complete, click **Apply Matrix**. The system computes a 3x3 decoupling matrix via `inverse(raw_matrix) * target_matrix` and saves it to `calibration_cfg.json` in the project root.
7. The matrix is automatically loaded on subsequent launches and injected into the hardware daemon.

Alternatively, you can manually edit the 3x3 matrix entries in the **Manual Calibration Matrix** grid and click **Save/Update Manual Parameters**.

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
}
```

The dashboard defaults to the **first key** in this dictionary. Move your most-used paradigm to the first position. For example, to default to `Grating`:

```python
PARADIGM_REGISTRY: Dict[str, type] = {
    "Grating": GratingParadigm,           # <-- now the default
    "Looming": LoomingParadigm,
    ...
}
```

### Change global default parameters (Subject ID, Resolution, ITI/ISI, etc.)

Open `src/ui/dashboard.py` and find the `_create_widgets` method. Search for the corresponding `ctk.StringVar(value="...")` and change the value string. Common examples:

| Parameter         | Line (approx.)                                            | Current Default | Change To                                   |
| ----------------- | --------------------------------------------------------- | --------------- | ------------------------------------------- |
| Subject ID        | `self.subject_var = ctk.StringVar(value="cricket_001")`   | `"cricket_001"` | Your lab's subject ID                       |
| Resolution        | `self.resolution_var = ctk.StringVar(value="3840,1080")`  | `"3840,1080"`   | Your screen resolution (e.g. `"1920,1080"`) |
| ITI Range         | `self.iti_range_var = ctk.StringVar(value="60-90")`       | `"60-90"`       | Your inter-trial interval (e.g. `"30-45"`)  |
| ISI Range         | `self.isi_range_var = ctk.StringVar(value="300-300")`     | `"300-300"`     | Your inter-session interval                 |
| Viewing Distance  | `self.viewing_distance_var = ctk.StringVar(value="30.0")` | `"30.0"`        | Your viewing distance in cm                 |
| Screen Width (cm) | `self.screen_width_cm_var = ctk.StringVar(value="53.0")`  | `"53.0"`        | Your screen physical width in cm            |

### Change paradigm-specific parameters (contrast, spatial frequency, speed, etc.)

Open `src/models/paradigm.py` and find the target paradigm class. Inside that class, locate the `get_parameter_schema(cls)` method. Each parameter is a dictionary entry — change the `"default"` value. Example for Grating spatial frequency:

```python
"Spatial Freq (cpd)": {
    "type": "float",
    "default": 0.05,      # <-- change this to your desired default
    "min": 0.001,
    "max": 10.0,
    "label": "Spatial Frequency (cpd)",
},
```

## 6. Data Output

Dual-track record files are automatically generated in the `data/` directory, aligned via `global_trial_id` and timestamps:

1. **`{Subject}_session_{n}_events.csv`** — Low-frequency experimental state events. Columns: `event_name`, `timestamp`, `session_num`, `trial_in_session`, `global_trial_id`, `details` (JSON).
2. **`{Subject}_session_{n}_kinematics.csv`** — High-frequency closed-loop telemetry. Columns: `sys_time`, `ard_time`, `dx`, `dy`, `dz`, `stim_state`, `global_trial_id`.

Both files share `global_trial_id` as the join key for cross-referencing trial-level events with frame-level kinematics.

## 7. Web Telemetry Mirror

The dashboard runs a lightweight real-time **web mirror** of its own state in a separate daemon process (`src/core/web_telemetry.py`, FastAPI + uvicorn). Any device on the same LAN can open the mirror in a browser — no experiment run is required; configuration and calibration are visible immediately.

### Access

- The mirror URL is shown in the dashboard status bar, e.g. `Web: http://192.168.1.10:8000`.
- The server binds `0.0.0.0:8000` (or the first free port at/above 8000) and serves a single-file frontend (`src/ui/static/index.html`).
- The browser page header has a **Copy State JSON** button for debugging.

### What it shows

- **Live status**: phase badge, session + trial progress (segmented bar), full hardware-state grid, worker status, and the dashboard status line.
- **Stimulus twin**: a 400×150 canvas replaying the stimulus render instructions (`ui_twin`).
- **Trajectory**: a 150×150 canvas plotting the recent path with the current heading arrow, plus θ/ω/D kinematics.
- **Calibration**: live raw DX/DY/DZ odometers, per-axis results checklist, and the manual 3×3 matrix.
- **Config**: all parameters, including dynamic paradigm params and kinematic trigger thresholds.

### Data protocol

The dashboard pushes a complete `full_state` JSON snapshot (`config`, `calibration`, `live`, `visual`) at up to 20 Hz over the WebSocket endpoint `/ws/full_state`. The frontend batches rendering via `requestAnimationFrame` and only rewrites changed DOM values.

### Notes

- The browser and the experiment PC must be on the same network.
- The frontend loads Tailwind / Lucide / Google Fonts from CDNs; on a fully offline network the layout degrades but data still updates.
- The web process is best-effort: a crash never affects the running experiment, and it self-heals within ~2 s.

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

```python
@classmethod
def get_available_patterns(cls) -> List[str]:
    return ["My Pattern A", "My Pattern B"]
```

- **`get_parameter_schema(cls)`**: Declare the dynamic UI parameter dictionary. The framework reads the `type` field to auto-generate dashboard form widgets. Supported types: `int`, `float`, `str`, `choice`, `bool`, `info`, `filepath`.

```python
@classmethod
def get_parameter_schema(cls) -> Dict[str, Dict[str, Any]]:
    return {
        "Speed (deg/s)": {
            "type": "float",
            "default": 30.0,
            "min": 0.1,
            "max": 1000.0,
            "label": "Speed (deg/s)",
        },
        "Execution Mode": {
            "type": "choice",
            "default": "Auto",
            "choices": ["Auto", "Manual", "Kinematic"],
            "label": "Execution Mode",
        },
    }
```

### Step 3: Implement Core Lifecycle

- **`generate_trials(self, pattern_key)`**: Construct and return the trial contexts (`List[dict]`) for the session based on the selected pattern.

- **`prepare_trial(self, trial_context)`**: Return hardware initialization serial commands before a trial starts (or an empty string `""`).

- **`get_idle_frame(self, hw_telemetry)`**: Return steady-state rendering instructions for ITI/ISI phases as `(cmds, telemetry_dict, sync_states)`.

- **`process_frame(self, elapsed_time, trial_context, hw_telemetry)`**: The frame-level closed-loop calculation core. Return the state tuple `(is_done, cmds, telemetry_dict, sync_states)` based on the timestamp and hardware telemetry.

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

**Rule 1 — Clock & Frame Tracking**

The paradigm class must maintain an internal frame counter to drive the frame-rate flash indicator. Reset `self._frame_counter = 0` in `prepare_trial` (or during trial initialization), and increment it on every `process_frame` call:

```python
def prepare_trial(self, trial_context):
    self._frame_counter = 0  # reset at trial start
    return ""

def process_frame(self, elapsed_time, trial_context, hw_telemetry):
    self._frame_counter += 1
    # ...
```

The counter powers the flash toggle: `odd = self._frame_counter % 2 == 1`.

**Rule 2 — Channel Physical Alignment**

| Screen Mode         | Block Count | Layout                                                                       |
| ------------------- | ----------- | ---------------------------------------------------------------------------- |
| **Dual (Surround)** | 4           | Left-bottom outer, left-bottom inner, right-bottom inner, right-bottom outer |
| **Single**          | 2           | Bottom-right corner: inner (trial state) + outer (frame flash), side-by-side |

- **Dual-screen paradigms** must append 4 sync blocks: the outermost blocks flash with frame rate, the inner blocks stay solid to indicate trial activation state.
- **Single-screen paradigms** must append exactly 2 sync blocks, both tightly placed in the bottom-right corner — the inner block shows trial state (solid), the outer block flashes with the frame rate.

```python
# Single-screen: call in process_frame / get_idle_frame
sync = self._build_sync_markers(stim_active, "single")
# Dual-screen: call in process_frame / get_idle_frame
sync = self._build_sync_markers(stim_active, "dual")
```

**Rule 3 — Layer Stacking Order**

All sync / photodiode `rect` commands **must be placed at the very end** of the `cmds` list. This guarantees they render on the absolute top layer and are never occluded by stimulus backgrounds, masks, or overlays.

```python
cmds = []  # stimulus drawing commands
cmds.append({...})  # circle, rect, element_array, etc.

# --- sync blocks MUST be appended last ---
sync = self._build_sync_markers(is_active, "single")  # or "dual"
cmds.extend(sync)
return cmds
```

**Reference Implementation** (`BaseParadigm._build_sync_markers`):

```python
def _build_sync_markers(self, is_active: bool, mode: str) -> list[dict]:
    off, on = [-1, -1, -1], [1, 1, 1]  # PsychoPy RGB
    odd = (self._frame_counter % 2 == 1)
    margin, w, h = 10, 60, 60
    half_w, half_h = self._win_w / 2.0, self._win_h / 2.0

    if mode == "single":
        # 2 blocks: bottom-right corner, side-by-side
        flash_color = on if (is_active and odd) else off
        active_color = on if is_active else off
        positions = [
            (half_w - margin - w * 1.5 - margin, -half_h + margin + h / 2),  # inner
            (half_w - margin - w / 2, -half_h + margin + h / 2),              # outer
        ]
        colors = [active_color, flash_color]
    elif mode == "dual":
        # 4 blocks: left-bottom pair + right-bottom pair
        outer_color = on if (is_active and odd) else off
        inner_color = on if is_active else off
        positions = [
            (-half_w + margin + w / 2, -half_h + margin + h / 2),
            (-half_w + margin + w * 1.5 + margin, -half_h + margin + h / 2),
            (half_w - margin - w * 1.5 - margin, -half_h + margin + h / 2),
            (half_w - margin - w / 2, -half_h + margin + h / 2),
        ]
        colors = [outer_color, inner_color, inner_color, outer_color]

    cmds = []
    for i, (pos, color) in enumerate(zip(positions, colors)):
        cmds.append({
            "id": f"_sync_{i}", "type": "rect",
            "width": w, "height": h, "pos": pos,
            "fillColor": color, "lineColor": color, "lineWidth": 0,
        })
    return cmds
```

### Step 5: Global Registration

Add the new class to the `PARADIGM_REGISTRY` dictionary at the bottom of `src/models/paradigm.py`:

```python
PARADIGM_REGISTRY: Dict[str, type] = {
    "Looming": LoomingParadigm,
    "ClassicLooming": ClassicLoomingParadigm,
    "OpticFlow": OpticFlowParadigm,
    "MovementTrace": MovementTraceParadigm,
    "Blank": BlankParadigm,
    "Grating": GratingParadigm,
    "SingleLooming": SingleLoomingParadigm,
    "MyParadigm": MyParadigm,  # <-- register here
}
```

The paradigm will appear in the dashboard dropdown on the next launch.
