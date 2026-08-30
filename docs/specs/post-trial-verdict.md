# Spec: Post-Trial Behavioral Verdict

## Problem Statement

After each trial, the experimenter has no real-time indication of whether the cricket responded to the stimulus. The raw kinematic data is logged, but determining response quality (escape, startle, no response) requires offline analysis. This makes it impossible to assess individual quality during the experiment — a cricket that never responds wastes an entire session before the experimenter discovers the problem.

## Solution

After each trial's PostStimulus window completes, the system automatically classifies the cricket's behavioral response using the accumulated kinematic data (displacement, turning angle) and:

1. Logs the verdict as a structured event in the ground truth log
2. Pushes it to the dashboard and web mirror as a discrete telemetry event
3. Displays a scrollable verdict history table showing all trials in the current session

The classification is a pure function of the `KinematicEngine` state at trial end — no additional sensor polling, no frame loop overhead, no impact on experiment timing (~50μs per trial).

## User Stories

1. As an experimenter, I want to see each trial's behavioral verdict (escape/startle/no_response) immediately after the trial ends, so that I can assess whether this cricket is responsive without waiting for offline analysis.
2. As an experimenter, I want to see a scrollable table of all verdicts in the current session, so that I can review the full response history even if I wasn't watching the screen during a particular trial.
3. As an experimenter, I want the verdict table to show the trial number, stimulus side, verdict label, cumulative displacement, and turning angle, so that I can quickly assess response magnitude.
4. As an experimenter, I want verdict rows color-coded by classification (escape=red, startle=orange, no_response=gray), so that I can scan the table at a glance.
5. As an experimenter, I want the verdict table to clear when a new session starts, so that I see only the current session's data.
6. As an experimenter, I want the same verdict table visible in the web mirror, so that I can monitor from a separate screen or device.
7. As an experimenter, I want the verdict logged to the ground truth CSV, so that offline analysis can reference the real-time classification.
8. As an experimenter running a Looming paradigm, I want escape/startle thresholds tuned for cricket looming responses (escape: >15mm displacement or >30° turn; startle: >5mm or >10°), so that the default classification is scientifically meaningful.
9. As an experimenter running a different paradigm, I want a sensible default classification that still reports displacement and angle, so that verdicts are available for all paradigm types.
10. As an advanced experimenter, I want to override classification thresholds via config without modifying code, so that I can adapt to different species or experimental conditions.
11. As a data analyst, I want each verdict event in the log to include the raw kinematic values (cum_disp, cum_dz, peak move_speed), so that I can re-classify offline with different thresholds.

## Implementation Decisions

### Classification function

- `BaseParadigm` gains a `classify_response(engine, trial_context, trial_duration) -> dict` method with a default three-way classification: escape (cum_disp > 15mm OR |cum_dz| > 30°), startle (cum_disp > 5mm OR |cum_dz| > 10°), no_response (otherwise).
- `LoomingParadigm` and `SingleLoomingParadigm` override with the same thresholds initially but can diverge as experiments evolve.
- Thresholds are read from config with fallback to paradigm defaults: `config.get("escape_threshold_mm", 15.0)` etc. No UI schema entry — advanced config only.
- The returned dict always includes: `response` (str), `cum_disp` (float), `cum_dz` (float), `peak_speed` (float).

### Worker integration

- In `GenericWorker.run()`, immediately after `logger.log_event("trial_stop", ...)` and before the next trial's ITI/wait/reset:
  - Call `self.paradigm.classify_response(self.kinematic_engine, trial, clock.getTime() - t_trial)`
  - Log via `logger.log_event("trial_verdict", clock.getTime(), **verdict)`
  - Push via `self._push({"action": "trial_verdict", "trial_idx": t_idx + 1, "side": trial.get("screen_side") or trial.get("direction") or trial.get("side", "—"), **verdict}, force=True)`
- The `force=True` push ensures the verdict is not dropped by the debounce/drain logic.
- A new action type `trial_verdict` is used (not `telemetry`) so it survives the "keep only latest telemetry" drain pattern in `_poll_telemetry`.

### Dashboard UI

- A new `verdict_frame` is inserted into the main layout between `status_frame` (row=1) and `status_bar` (row=2), shifting status_bar and ctrl_frame down by one row.
- The frame contains a `ttk.Treeview` with columns: `#`, `Side`, `Verdict`, `Δ mm`, `θ °`.
- Dark theme styling applied via `ttk.Style` to match the CustomTkinter dark palette.
- Verdict rows are tagged by classification for color coding: escape=red, startle=orange, no_response=gray.
- `_poll_telemetry` gains a handler for `action == "trial_verdict"` that inserts a row into the Treeview.
- The Treeview is cleared in `_reset_ui()` (experiment end) and when a new session starts (detected via session_num change in telemetry).

### Web bridge

- `MasterDashboard` gains a `_verdict_history: list[dict]` accumulator, appended on each `trial_verdict` event, cleared on session change / experiment end.
- `WebBridge.build_full_state()` includes a new `verdicts` key containing this list.
- `WebBridge.get_live_state()` includes a `verdict_summary` dict: `{escape: N, startle: N, no_response: N}` for the header or status area.

### Web mirror (index.html)

- A new `c-12` bento card is added as the fourth row, after Live Status / Twin / Trajectory.
- Contains a `<table>` with sticky `<thead>` and scrollable `<tbody>` (max-height ~200px).
- Columns: `#`, `Side`, `Verdict`, `Δ mm`, `θ °`.
- Verdict cells use color-coded chips (existing `.chip` CSS classes extended with `.chip-escape`, `.chip-startle`, `.chip-none`).
- Rows are rebuilt from the `verdicts` array in `renderLow()` (150ms throttle — adequate for per-trial events).

### Performance impact

- Classification: ~50μs per trial (pure arithmetic on pre-allocated float slots).
- Queue push: one `put(force=True)` per trial (~10μs).
- Total overhead per 18-trial session: < 1ms. Undetectable in experiment timing.

## Testing Decisions

### What makes a good test here

Tests verify the **classification boundary** through the public `classify_response` interface. They don't test internal KinematicEngine accumulation, queue routing, or UI rendering. Expected values are independent literals (known displacement → known verdict), not recomputed from the classification logic.

### Seam under test

**`BaseParadigm.classify_response(engine, trial_context, trial_duration) → dict`**

This is a pure function boundary:
- Input: a `KinematicEngine` with known accumulated values + trial context dict + elapsed time
- Output: a verdict dict
- No side effects, no I/O, no GUI, no PsychoPy

### Test cases

1. Engine with zero displacement/angle → `no_response`
2. Engine with displacement just above escape threshold → `escape`
3. Engine with angle just above escape threshold → `escape`
4. Engine with displacement in startle range → `startle`
5. Engine with angle in startle range → `startle`
6. Paradigm-specific override returns same structure
7. Returned dict always contains required keys (`response`, `cum_disp`, `cum_dz`, `peak_speed`)

### Prior art

No existing test files in the repo. This will be the first test module at `tests/test_verdict.py`.

## Out of Scope

- **Freeze detection** — requires buffering per-frame velocity time series during PostStimulus. Deferred; the `classify_response` hook supports future extension.
- **Adaptive flow control** — "pause after N consecutive no_response" is a separate feature that could consume verdicts but is not part of this spec.
- **Staircase / threshold tracking** — adjusting trial parameters based on verdict history is a fundamentally different feature.
- **Per-trial latency measurement** — requires identifying the exact frame of response onset within PostStimulus, not just cumulative values at trial end.
- **Customizable column set** — the 5-column layout is fixed for now.

## Further Notes

- The `classify_response` method on `BaseParadigm` is deliberately a method (not a standalone function) so that paradigm subclasses can override thresholds or classification logic without modifying core infrastructure — consistent with the Paradigm Extension Boundary in `src/models/BOUNDARY.md`.
- The verdict dict is intentionally flat (no nested objects) so it serializes cleanly to both CSV log events and JSON telemetry.
- Session-level verdict clearing is tied to `session_num` change detection in the dashboard, not to a new telemetry action — minimizing worker-side changes.
