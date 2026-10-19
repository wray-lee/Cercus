# 01: Correct Looming pattern angles (l/v = 120 ms) and add 25° / TTC −541 ms pattern

**What to build:** The Looming paradigm's pattern dropdown shows the visual angle actually on screen at wind onset under l/v = 120 ms, and offers a new 25° / TTC −541 ms condition placed first in the TTC gradient. Trigger delays for existing patterns are unchanged. Spec: `docs/specs/looming-pattern-angles-and-traj-jitter.md`.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Looming patterns renamed: TTC −373ms / 35.7°, −308ms / 42.6°, −261ms / 49.4°, −225ms / 56.1°, −119ms / 90.5°; 0ms / 180° and +200ms unchanged
- [x] New pattern "Looming + Wind (TTC -541ms / 25°)" (looming_wind, l/v 120) ordered before −373 ms
- [x] Test: for every negative-TTC looming_wind pattern, angle parsed from label equals 2·atan(l/v ÷ |TTC|) within ±0.1°
- [x] Test: 25° pattern generates balanced L/R trials and `prepare_trial` returns `<L|R,6334>` (±1 ms)
- [x] Existing patterns' wind delays unchanged (test)
- [x] SingleLooming patterns untouched
- [x] `docs/pattern.md` (angles, 10 patterns) and both READMEs (8 conditions from TTC −541 ms) updated
