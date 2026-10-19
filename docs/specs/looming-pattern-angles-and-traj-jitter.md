# Spec: Looming pattern angle correction, 25° subliminal pattern, trajectory jitter fix

## Problem Statement

The Looming paradigm classifies its patterns by wind trigger delay (TTC offset). The trigger delays are correct, but the pattern labels still carry the visual angles computed for the old l/v = 100 ms. Since l/v was raised to 120 ms, every angle in the pattern names is wrong (e.g. TTC −373 ms is labelled 30° but the disc actually subtends 35.7° at that moment). Experimenters choosing a pattern, and anyone reading the logged `Experiment Pattern` afterward, see a stimulus angle that was never shown.

The experiment also needs a new, earlier condition to probe possible subliminal (threshold-level) visual integration: wind at 25° (TTC −541 ms), which does not exist today.

Separately, the Dashboard trajectory view has a long-standing defect: while the trace auto-zooms (and when the window/page is resized), the trajectory line wobbles in a jelly-like way instead of staying a stable path.

## Solution

- Rename the Looming patterns so each label states the angle that is actually on screen at its TTC under l/v = 120 ms. Trigger delays stay as they are.
- Add one pattern: Looming + Wind at TTC −541 ms / 25°.
- Make the trajectory canvas draw a stable path: the same physical trail always produces the same polyline, regardless of how many points are buffered or how the view is scaled, and resizes redraw immediately at the new size.

Correct pattern set (l/v = 120 ms, θ = 2·atan(l/v ÷ |TTC|)):

| Pattern | TTC (ms) | θ at wind onset |
|---|---|---|
| Baseline Visual | — | — |
| Baseline Wind | — | — |
| Looming + Wind (TTC −541ms / 25°) — **new** | −541 | 25.0° |
| Looming + Wind (TTC −373ms / 35.7°) | −373 | 35.7° |
| Looming + Wind (TTC −308ms / 42.6°) | −308 | 42.6° |
| Looming + Wind (TTC −261ms / 49.4°) | −261 | 49.4° |
| Looming + Wind (TTC −225ms / 56.1°) | −225 | 56.1° |
| Looming + Wind (TTC −119ms / 90.5°) | −119 | 90.5° |
| Looming + Wind (TTC 0ms / 180°) | 0 | 180° |
| Looming + Wind (TTC +200ms) | +200 | — |

## User Stories

1. As an experimenter, I want the Looming pattern dropdown to show the true visual angle at wind onset, so that I pick conditions by the stimulus the cricket actually sees.
2. As an experimenter, I want the angles to match l/v = 120 ms, so that the labels agree with the stimulus timing the system renders.
3. As an experimenter, I want a 25° / TTC −541 ms pattern, so that I can test whether a small, possibly subliminal looming stimulus modulates the wind response.
4. As an experimenter, I want the new pattern ordered with the other TTC conditions (earliest first), so that the dropdown reads as a monotonic TTC gradient.
5. As an experimenter, I want the new pattern to use the same left/right balanced, max-2-in-a-row randomisation as the others, so that it is directly comparable.
6. As an experimenter, I want the new pattern to honour Number of Repetitions and Random Seed like the others, so that sessions are reproducible.
7. As an experimenter, I want the wind trigger delay for each pattern to remain t_col + TTC, so that renaming does not change any already-collected condition.
8. As an analyst, I want the logged `Experiment Pattern` string to carry the correct angle, so that data files are self-describing.
9. As an analyst, I want the trial context to still carry `target_ttc_ms` and `lv_ratio_ms`, so that analysis keys off numbers, not label text.
10. As an analyst, I want Baseline Wind's wind onset aligned with the l/v = 120 ms collision time, so that the wind-only baseline has the same pre-stimulus duration as the looming conditions.
11. As a maintainer, I want the label angles to be verifiable from l/v and TTC by a test, so that a future l/v change cannot silently leave labels stale again.
12. As a maintainer, I want the protocol document (pattern list, pattern count) and the READMEs updated, so that the docs describe the same 10 patterns as the code.
13. As an experimenter watching the Dashboard, I want the trajectory to grow as a stable line while it auto-zooms, so that I can read the cricket's path in real time.
14. As an experimenter, I want the trajectory to stay stable once the trail exceeds the buffer limit and starts sliding, so that long trials remain readable.
15. As an experimenter, I want resizing the Dashboard window or changing page zoom to redraw the trajectory crisply at the new size, without a stretched intermediate frame.
16. As a Monitor viewer on the LAN, I want the same stable trajectory, since the Monitor uses the same canvas component.
17. As an experimenter, I want the heading arrow to stay attached to the latest point during zoom, so that orientation is readable.

## Implementation Decisions

**Looming paradigm patterns (Looming paradigm only)**
- Edit the Looming paradigm's pattern table: rename the five angle-bearing keys to the corrected angles above, add the TTC −541 ms / 25° entry (type `looming_wind`, `lv_ratio_ms` 120) placed before −373 ms.
- No change to trial generation, the wind command format (`<L|R,delay_ms>`), or the delay formula `delay = round(l/v ÷ tan(init_deg/2)) + TTC`. With l/v = 120 ms and init 2°, t_col ≈ 6875 ms, so the new pattern triggers at ≈ 6334 ms — well positive, no clamping.
- Angle labels use one decimal place except exact values (25°, 180°), matching the list the user supplied.
- Baseline Wind currently hardcodes l/v = 100 ms when computing its equivalent pre-stimulus delay (≈ 5.73 s), which no longer matches the 120 ms looming lead time (≈ 6.88 s). Align it to 120 ms. Lazy form: derive from the same l/v value the looming patterns use rather than a second literal.
- Pattern keys are the persisted identifier in configs/logs. Old keys are not aliased (see Out of Scope).

**SingleLooming paradigm**
- Unchanged. It still uses l/v = 100 ms, for which its existing labels (30°, 36°, …) are correct.

**Trajectory canvas (shared by Dashboard and Monitor)**
- Root cause 1 — unstable decimation: when the trail exceeds 200 points the renderer keeps every `step`-th point by index *within the current window*. `step = ceil(n/200)` changes as n grows, and once the 1000-point buffer slides, index 0 shifts every update. Either way a different subset of points is drawn each frame, so the polyline re-shapes continuously → jelly wobble, amplified by auto-zoom. Fix: drop the decimation (1000 points is trivial for a 2D canvas). If decimation is ever needed again, it must be anchored to an absolute sample index, not window position.
- Root cause 2 — resize without redraw: the bitmap is only resized/redrawn when Python pushes new data, and Python skips pushes when the trail is unchanged. On window resize / browser zoom the browser stretches the stale bitmap until the next data change. Fix: the JS renderer keeps the last payload per canvas and redraws on a `ResizeObserver` callback.
- Auto-zoom behaviour (monotonic bbox per trial, 10 % margin, min span) stays as is.

## Testing Decisions

- Good tests assert external behaviour through the paradigm's public interface only: the list of available patterns, the trials produced for a pattern, and the wind command string returned by `prepare_trial`. No asserting on internal attributes.
- Seam 1 — Looming paradigm public API (existing seam, unit tests in the existing paradigm/worker test style):
  - For every `looming_wind` pattern with negative TTC, parse the angle out of the label and assert it equals 2·atan(l/v ÷ |TTC|) within rounding (±0.1°). This is the regression guard for story 11.
  - The 25° pattern exists, generates balanced left/right trials, and its `prepare_trial` returns `<L|R,6334>` (±1 ms).
  - Baseline Wind's `prepare_trial` delay equals the looming t_col for l/v = 120 ms.
- Seam 2 — trajectory canvas: there is no JS test harness in the repo and none will be added. Verify in the running app (Dashboard + Monitor): synthetic trail through the mock serial generator, watch the trace while it auto-zooms and past 1000 points, and resize the window / Ctrl± zoom. Acceptance: no visible wobble of already-drawn path segments; resize redraws at once.
- Prior art: `tests/test_stimulus_worker.py`, `tests/test_controller.py` (paradigm usage), `tests/test_trajectory.py` (Python-side trail state, unchanged by this work).

## Out of Scope

- Aliasing or migrating old pattern names in previously saved configs/logs; old data keeps its old (wrong-angle) label and is re-interpreted via `target_ttc_ms`.
- Changing SingleLooming patterns or its l/v.
- Exposing l/v as a user parameter for the Looming paradigm.
- Changes to ITI/ISI, repetitions, or the 2° start angle.
- Python-side trajectory state (bbox, jump gate, buffer size).

## Further Notes

- Pattern count becomes 10 (2 baselines + 8 TTC conditions); the protocol document's "Totally 9 patterns" and READMEs' "7 conditions from TTC −373 ms" need updating.
- The Baseline Wind alignment (l/v 100 → 120) changes that baseline's wind onset from ≈ 5.73 s to ≈ 6.88 s. This is a behaviour change for future sessions; it is included because the baseline is defined as "aligned to the looming lead time".
- 25° at TTC −541 ms is still far above the 2° start angle, so the disc is visibly expanding at wind onset; "subliminal" here refers to the hypothesis under test, not to a rendering change.
