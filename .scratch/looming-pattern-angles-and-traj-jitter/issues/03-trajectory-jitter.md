# 03: Stable trajectory canvas during auto-zoom and resize

**What to build:** On Dashboard and Monitor, the trajectory grows as a stable line while it auto-zooms and after the 1000-point buffer starts sliding; resizing the window or page zoom redraws crisply at once. Root causes: window-relative modulo decimation (subset changes every frame) and redraw only on new data. Spec: `docs/specs/looming-pattern-angles-and-traj-jitter.md`.

**Blocked by:** None (can start immediately)

**Status:** needs-manual-verification

- [x] Decimation removed (or anchored to absolute sample index) — already-drawn segments never re-shape
- [x] Renderer keeps last payload per canvas and redraws on ResizeObserver
- [x] Heading arrow stays on the latest point
- [ ] Manual verification in running app (Dashboard + Monitor): no wobble during auto-zoom, past 1000 points, and on resize/Ctrl± zoom
