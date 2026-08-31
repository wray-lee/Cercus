# ADR 0005: Real-Time Post-Trial Behavioral Verdict Classification

## Status
Accepted

## Date
2025-02-28

## Context
During behavioral sessions, experimenters need real-time assessment of insect responsiveness (e.g. escape, startle, or no response) to evaluate animal condition and data quality without having to wait for offline post-processing.

## Decision
Introduce an extensible post-trial classification hook in `BaseParadigm`:
- `BaseParadigm.classify_response(engine, trial_context, trial_duration) -> dict` evaluates accumulated displacement and turning angle from `KinematicEngine` at the end of each trial.
- Default three-way classification logic:
  - `escape`: displacement > 15 mm or turning angle > 30°.
  - `startle`: displacement > 5 mm or turning angle > 10°.
  - `no_response`: below startle thresholds.
- Thresholds are configurable via experiment configuration parameters.
- At the end of each trial, the worker logs `trial_verdict` to the ground truth CSV and pushes the verdict to the UI telemetry queue.
- `AppState` aggregates session verdicts and renders real-time color-coded tables in both `/dashboard` and `/monitor`.

## Consequences
### Positive
- Instant experimental feedback for the researcher on insect responsiveness.
- Zero frame-loop overhead (~50 microseconds executed once per trial).
- Structured logging of behavioral verdicts alongside raw kinematic logs.

### Negative / Trade-offs
- Fixed heuristic thresholds may need per-species or per-paradigm calibration.
