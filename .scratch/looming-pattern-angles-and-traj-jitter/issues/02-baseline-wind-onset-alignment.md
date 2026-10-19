# 02: Align Baseline Wind onset to the l/v = 120 ms lead time

**What to build:** The Looming paradigm's Baseline Wind trial fires wind at the same pre-stimulus time as the looming collision (≈ 6875 ms) instead of the stale l/v = 100 ms value (≈ 5730 ms). The delay derives from the same l/v the looming patterns use, not a second literal. Spec: `docs/specs/looming-pattern-angles-and-traj-jitter.md`.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Test: Baseline Wind `prepare_trial` delay equals round(120 ÷ tan(1°)) ms ≈ 6875 for the Looming paradigm
- [x] No second hardcoded l/v literal for the baseline in the Looming paradigm
- [x] SingleLooming unchanged
