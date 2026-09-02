import collections
import csv
import json
import os
import threading
from typing import Any, List, Optional

import numpy as np

DEFAULT_MAX_KINEMATICS_BATCHES: int = 1000


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that converts numpy types to standard Python primitives."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class GroundTruthLogger:
    """Asynchronous ground-truth event and kinematics CSV logger with bounded memory.

    Architecture & Tradeoff:
    - Dual-channel design:
      1. Critical Event & Control Channel (unbounded): Lifecycle commands (`open_session`,
         `close`, `save_cache`, `flush`, shutdown poison pill) and paradigm events
         (`trial_start`, `stimulus_onset`, `trial_stop`, `trial_verdict`) are never dropped.
      2. Bulk Kinematics Channel (bounded): High-frequency kinematics batches are buffered up
         to `max_kinematics_batches`. Under an unrecoverable disk stall or sustained I/O
         backpressure, excess kinematics batches are dropped non-blockingly to bound memory
         growth and prevent blocking the real-time stimulus rendering loop.
      - Tradeoff: Zero data loss is NOT claimed during an impossible sustained disk stall;
        instead, bulk kinematics data is explicitly shed while tracking observable drop
        counts (`dropped_kinematics_batches`, `dropped_kinematics_rows`), while critical
        experiment metadata and session lifecycles remain completely intact.
    """

    EVENT_COLUMNS = [
        "event_name",
        "timestamp",
        "session_num",
        "trial_in_session",
        "global_trial_id",
        "details",
    ]

    def __init__(
        self,
        output_dir: str,
        max_kinematics_batches: int = DEFAULT_MAX_KINEMATICS_BATCHES,
    ) -> None:
        self.out = output_dir
        os.makedirs(self.out, exist_ok=True)
        self.global_trial_id = self._load_cache()
        self.session_num = 0
        self.trial_in_session = 0
        self._event_file = None
        self._event_writer = None
        self._kinematics_file = None
        self._kinematics_writer = None
        self._session_open = False

        self._max_kinematics_batches = max(1, max_kinematics_batches)
        self._dropped_kinematics_batches = 0
        self._dropped_kinematics_rows = 0

        # Synchronization and dual-channel queues
        self._lock = threading.RLock()
        self._not_empty = threading.Condition(self._lock)
        self._control_items: collections.deque = collections.deque()
        self._kin_items: collections.deque = collections.deque()

        # Dedicated background writer daemon
        self._writer_thread = threading.Thread(
            target=self._io_loop, daemon=True
        )
        self._writer_thread.start()

    @property
    def dropped_kinematics_batches(self) -> int:
        """Total number of kinematics batches dropped due to backpressure."""
        with self._lock:
            return self._dropped_kinematics_batches

    @property
    def dropped_kinematics_rows(self) -> int:
        """Total number of individual kinematics rows/samples dropped."""
        with self._lock:
            return self._dropped_kinematics_rows

    @property
    def dropped_kinematics_count(self) -> int:
        """Alias for dropped kinematics batches."""
        with self._lock:
            return self._dropped_kinematics_batches

    def _load_cache(self) -> int:
        cache_path = os.path.join(self.out, ".trial_cache.txt")
        if os.path.exists(cache_path):
            try:
                return int(open(cache_path, "r").read().strip())
            except (ValueError, IOError):
                return 0
        return 0

    # ------------------------------------------------------------------
    # Writer daemon – consumes all disk-I/O commands off the main thread
    # ------------------------------------------------------------------

    def _do_close(self) -> None:
        if self._event_file:
            try:
                self._event_file.flush()
                os.fsync(self._event_file.fileno())
                self._event_file.close()
            except Exception:
                pass
            self._event_file, self._event_writer = None, None
        if self._kinematics_file:
            try:
                self._kinematics_file.flush()
                os.fsync(self._kinematics_file.fileno())
                self._kinematics_file.close()
            except Exception:
                pass
            self._kinematics_file, self._kinematics_writer = None, None

    def _drain_pending_kinematics(self) -> None:
        """Drain all currently queued kinematics batches to the active writer."""
        while True:
            with self._lock:
                if not self._kin_items:
                    break
                batch = self._kin_items.popleft()
            if self._kinematics_writer:
                try:
                    self._kinematics_writer.writerows(batch)
                except Exception:
                    pass

    def _io_loop(self) -> None:
        while True:
            with self._lock:
                while not self._control_items and not self._kin_items:
                    self._not_empty.wait()

                # Prioritize control and lifecycle commands over kinematics
                if self._control_items:
                    item = self._control_items.popleft()
                    is_control = True
                else:
                    item = self._kin_items.popleft()
                    is_control = False

            if not is_control:
                # Bulk kinematics batch item
                if self._kinematics_writer:
                    try:
                        self._kinematics_writer.writerows(item)
                    except Exception:
                        pass
                continue

            # Control / Event item
            if item is None:  # Poison pill
                self._drain_pending_kinematics()
                self._do_close()
                break

            action, payload = item
            try:
                if action == "open_session":
                    self._do_close()
                    subject_id, session_num, kin_headers = payload
                    base_name = f"{subject_id}_session_{session_num}"

                    event_path = os.path.join(self.out, f"{base_name}_events.csv")
                    event_exists = os.path.exists(event_path) and os.path.getsize(event_path) > 0
                    self._event_file = open(event_path, "a", newline="", encoding="utf-8-sig")
                    self._event_writer = csv.writer(self._event_file)
                    if not event_exists:
                        self._event_writer.writerow(self.EVENT_COLUMNS)

                    kinematics_path = os.path.join(self.out, f"{base_name}_kinematics.csv")
                    kin_exists = os.path.exists(kinematics_path) and os.path.getsize(kinematics_path) > 0
                    self._kinematics_file = open(
                        kinematics_path, "a", newline="", encoding="utf-8-sig"
                    )
                    self._kinematics_writer = csv.writer(self._kinematics_file)
                    if not kin_exists:
                        self._kinematics_writer.writerow(kin_headers)

                elif action == "close":
                    self._drain_pending_kinematics()
                    self._do_close()
                    if payload:
                        payload.set()

                elif action == "event_row":
                    if self._event_writer:
                        # payload: (event_name, ts, session, trial, gid, details_dict)
                        # json.dumps serialized on background thread, keeping main loop non-blocking
                        *head, details = payload
                        row = [*head, json.dumps(details, cls=NumpyEncoder) if details else ""]
                        self._event_writer.writerow(row)

                elif action == "flush_kin":
                    self._drain_pending_kinematics()
                    if self._kinematics_file:
                        self._kinematics_file.flush()
                        os.fsync(self._kinematics_file.fileno())

                elif action == "flush_event":
                    if self._event_file:
                        self._event_file.flush()
                        os.fsync(self._event_file.fileno())

                elif action == "save_cache":
                    cache_path = os.path.join(self.out, ".trial_cache.txt")
                    with open(cache_path, "w") as f:
                        f.write(str(payload))

                elif action == "flush_sync":
                    self._drain_pending_kinematics()
                    if self._event_file:
                        self._event_file.flush()
                        os.fsync(self._event_file.fileno())
                    if self._kinematics_file:
                        self._kinematics_file.flush()
                        os.fsync(self._kinematics_file.fileno())
                    if payload:
                        payload.set()

            except Exception:
                pass  # never crash the writer thread

    # ------------------------------------------------------------------
    # Public API – all callers stay on the main thread; I/O is queued
    # ------------------------------------------------------------------

    def open_session(self, subject_id: str, session_num: int, kin_headers: List[str]) -> None:
        self.session_num = session_num
        self.trial_in_session = 0
        self._session_open = True
        with self._lock:
            self._control_items.append(("open_session", (subject_id, session_num, kin_headers)))
            self._not_empty.notify()

    def is_open(self) -> bool:
        return self._session_open

    def close(self, timeout: Optional[float] = None) -> bool:
        """Flush pending writes and close current session files (thread stays alive)."""
        if self._session_open:
            self._session_open = False
            done = threading.Event()
            with self._lock:
                self._control_items.append(("close", done))
                self._not_empty.notify()
            return done.wait(timeout=timeout)
        return True

    def shutdown(self, timeout: Optional[float] = None) -> None:
        """Final shutdown: flush everything, stop writer thread, close files."""
        self.close(timeout=timeout)
        with self._lock:
            self._control_items.append(None)  # poison pill
            self._not_empty.notify()
        self._writer_thread.join(timeout=timeout)

    def advance_trial(self) -> None:
        self.trial_in_session += 1
        self.global_trial_id += 1
        with self._lock:
            self._control_items.append(("save_cache", self.global_trial_id))
            self._not_empty.notify()

    def log_event(self, event_name: str, timestamp: float, **details: Any) -> None:
        """Enqueue an event row. Serialization is deferred to the I/O thread.

        Critical events use the unbounded control channel and are never dropped.
        """
        if not self._session_open:
            return
        with self._lock:
            self._control_items.append(("event_row", (
                event_name,
                f"{timestamp:.6f}",
                self.session_num,
                self.trial_in_session,
                self.global_trial_id,
                details,
            )))
            self._not_empty.notify()

    def log_kinematics_batch(self, items: List[List[Any]]) -> None:
        """Enqueue a kinematics batch to the bounded bulk kinematics channel.

        Nonblocking: If queue capacity is reached, incoming batch is dropped and
        drop counts are incremented without stalling the caller.
        """
        if not self._session_open or not items:
            return
        with self._lock:
            if len(self._kin_items) >= self._max_kinematics_batches:
                self._dropped_kinematics_batches += 1
                self._dropped_kinematics_rows += len(items)
                return
            self._kin_items.append(items)
            self._not_empty.notify()

    def flush_kinematics(self) -> None:
        with self._lock:
            self._control_items.append(("flush_kin", None))
            self._not_empty.notify()

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Block until all prior queued writes are flushed to disk."""
        done = threading.Event()
        with self._lock:
            self._control_items.append(("flush_sync", done))
            self._not_empty.notify()
        return done.wait(timeout=timeout)
