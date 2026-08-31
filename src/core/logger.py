import csv
import json
import os
import queue
import threading
from typing import Any, List

import numpy as np


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
    """Asynchronous ground-truth event and kinematics CSV logger."""

    EVENT_COLUMNS = [
        "event_name",
        "timestamp",
        "session_num",
        "trial_in_session",
        "global_trial_id",
        "details",
    ]

    def __init__(self, output_dir: str) -> None:
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

        # Async I/O: dedicated writer thread with queue
        self._io_queue: queue.Queue = queue.Queue()
        self._writer_thread = threading.Thread(
            target=self._io_loop, daemon=True
        )
        self._writer_thread.start()

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

    def _do_close(self):
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

    def _io_loop(self):
        while True:
            item = self._io_queue.get()
            if item is None:  # poison pill
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
                    self._do_close()
                    if payload:
                        payload.set()
                elif action == "event_row":
                    if self._event_writer:
                        # payload: (event_name, ts, session, trial, gid, details_dict)
                        # json.dumps 在后台线程执行，不阻塞渲染主线程
                        *head, details = payload
                        row = [*head, json.dumps(details, cls=NumpyEncoder) if details else ""]
                        self._event_writer.writerow(row)
                elif action == "kin_rows":
                    if self._kinematics_writer:
                        self._kinematics_writer.writerows(payload)
                elif action == "flush_event":
                    if self._event_file:
                        self._event_file.flush()
                        os.fsync(self._event_file.fileno())
                elif action == "flush_kin":
                    if self._kinematics_file:
                        self._kinematics_file.flush()
                        os.fsync(self._kinematics_file.fileno())
                elif action == "save_cache":
                    cache_path = os.path.join(self.out, ".trial_cache.txt")
                    with open(cache_path, "w") as f:
                        f.write(str(payload))
                elif action == "flush_sync":
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
        self._io_queue.put(("open_session", (subject_id, session_num, kin_headers)))

    def is_open(self) -> bool:
        return self._session_open

    def close(self) -> None:
        """Flush pending writes and close current session files (thread stays alive)."""
        if self._session_open:
            self._session_open = False
            done = threading.Event()
            self._io_queue.put(("close", done))
            done.wait()

    def shutdown(self) -> None:
        """Final shutdown: flush everything, stop writer thread, close files."""
        self.close()
        self._io_queue.put(None)  # poison pill
        self._writer_thread.join()

    def advance_trial(self) -> None:
        self.trial_in_session += 1
        self.global_trial_id += 1
        self._io_queue.put(("save_cache", self.global_trial_id))

    def log_event(self, event_name: str, timestamp: float, **details: Any) -> None:
        """Enqueue an event row.  Serialization is deferred to the I/O thread."""
        if not self._session_open:
            return
        # 主线程仅打包原始数据，不做 json.dumps；序列化在 _io_loop 后台完成
        self._io_queue.put(("event_row", (
            event_name,
            f"{timestamp:.6f}",
            self.session_num,
            self.trial_in_session,
            self.global_trial_id,
            details,  # raw dict — _io_loop will serialize
        )))

    def log_kinematics_batch(self, items: List[List[Any]]) -> None:
        if not self._session_open:
            return
        self._io_queue.put(("kin_rows", items))

    def flush_kinematics(self) -> None:
        self._io_queue.put(("flush_kin", None))

    def flush(self) -> None:
        """Block until all prior queued writes are flushed to disk."""
        self._io_queue.put(("flush_event", None))
        self._io_queue.put(("flush_kin", None))
        done = threading.Event()
        self._io_queue.put(("flush_sync", done))
        done.wait()
