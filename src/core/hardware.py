import queue
import threading
import time
from typing import List, Tuple, Callable, Union

try:
    import serial

    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    serial = None


class KinematicsParser:
    _DEFAULT_SCHEMA = [
        (0, 0, "ard_time"),
        (1, 0, "dx"),
        (2, 0, "dy"),
        (3, 0, "dz"),
        (4, 0, "stim_state"),
    ]

    _IDENTITY_MATRIX = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    def __init__(self, telemetry_schema: list = None, calib_factors: dict = None):
        self._field_defs = telemetry_schema or self._DEFAULT_SCHEMA
        self._calib_factors = calib_factors or {"dx": 1.0, "dy": 1.0, "dz": 1.0}
        self._calib_matrix = [row[:] for row in self._IDENTITY_MATRIX]
        self._spatial_accum: dict[str, float] = {"dx": 0.0, "dy": 0.0, "dz": 0.0}
        # 防抖阈值
        # self._jitter_thresh: float = 1.5
        self._jitter_thresh: float = 0.0
        # Pre-computed index map for zero-allocation calibration
        self._idx_map: dict[str, int] = {}
        for idx, (_, _, key) in enumerate(self._field_defs):
            if key in ("dx", "dy", "dz"):
                self._idx_map[key] = idx
        self._has_spatial = all(k in self._idx_map for k in ("dx", "dy", "dz"))
        # Reusable output buffer (avoids list() allocation per frame)
        self._out_buf: list = [d for _, d, _ in self._field_defs]

    def get_headers(self) -> list:
        return ["sys_time"] + [h for _, _, h in self._field_defs] + ["global_trial_id"]

    @staticmethod
    def _safe_int(val: str, default: int = 0):
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    def _parse_fields(self, raw: str):
        parts = raw.split(",")
        out = []
        for i, d, _ in self._field_defs:
            if i < len(parts):
                v = self._safe_int(parts[i], d)
                if v is None:
                    return None
                out.append(v)
            else:
                out.append(d)
        return out

    def _apply_calibration(self, fields: list) -> list:
        # Reuse pre-allocated output buffer instead of list(fields)
        out = self._out_buf
        for i in range(len(fields)):
            out[i] = fields[i]
        idx_map = self._idx_map
        if self._has_spatial:
            raw_dx = float(out[idx_map["dx"]])
            raw_dy = float(out[idx_map["dy"]])
            raw_dz = float(out[idx_map["dz"]])

            # Spatial hysteresis accumulator: suppress sub-threshold jitter
            # while preserving true displacement via frame-to-frame accumulation.
            accum = self._spatial_accum
            accum["dx"] += raw_dx
            accum["dy"] += raw_dy
            accum["dz"] += raw_dz

            thresh = self._jitter_thresh
            valid_dx: float = accum["dx"] if abs(accum["dx"]) >= thresh else 0.0
            valid_dy: float = accum["dy"] if abs(accum["dy"]) >= thresh else 0.0
            valid_dz: float = accum["dz"] if abs(accum["dz"]) >= thresh else 0.0

            if valid_dx != 0.0:
                accum["dx"] = 0.0
            if valid_dy != 0.0:
                accum["dy"] = 0.0
            if valid_dz != 0.0:
                accum["dz"] = 0.0

            # Apply calibration decoupling matrix to validated displacements
            m: list[list[float]] = self._calib_matrix
            real_dx: float = valid_dx * m[0][0] + valid_dy * m[0][1] + valid_dz * m[0][2]
            real_dy: float = valid_dx * m[1][0] + valid_dy * m[1][1] + valid_dz * m[1][2]
            real_dz: float = valid_dx * m[2][0] + valid_dy * m[2][1] + valid_dz * m[2][2]

            out[idx_map["dx"]] = real_dx
            out[idx_map["dy"]] = real_dy
            out[idx_map["dz"]] = real_dz
        # Apply legacy scalar factors for non-dx/dy/dz fields
        for idx, (_, _, key) in enumerate(self._field_defs):
            if key in ("dx", "dy", "dz"):
                continue
            factor = self._calib_factors.get(key)
            if factor is not None and factor != 1.0:
                val = out[idx]
                if isinstance(val, (int, float)) and val != 0:
                    out[idx] = float(val) * factor
        return out

    def set_calib_factors(self, factors: dict):
        self._calib_factors.update(factors)

    def set_calib_matrix(self, matrix: list):
        """Set the 3x3 decoupling calibration matrix.

        Args:
            matrix: 3x3 list of lists. Each row transforms one output axis:
                    [real_dx, real_dy, real_dz] = [raw_dx, raw_dy, raw_dz] dot matrix
        """
        self._calib_matrix = [row[:] for row in matrix]

    def parse(self, sys_time: float, raw: str, g_id: int):
        raw = raw.strip()
        if not raw:
            return None
        fields = self._parse_fields(raw)
        if fields is None:
            return None
        fields = self._apply_calibration(fields)
        return [f"{sys_time:.6f}"] + fields + [g_id]

    def get_telemetry(self, raw: str):
        raw = raw.strip()
        if not raw:
            return None
        fields = self._parse_fields(raw)
        if fields is None:
            return None
        fields = self._apply_calibration(fields)
        keys = [h for _, _, h in self._field_defs]
        return dict(zip(keys, fields))


class SerialDaemon:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.05):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.data_queue = queue.Queue(maxsize=8192)
        self.tx_queue = queue.Queue(maxsize=128)
        self._serial = None
        self._running = False
        self._clock_offset: float = 0.0
        self._rx_buf: str = ""
        self._flush_event = threading.Event()

    def start(self, time_func: Callable[[], float]):
        if time_func is None:
            raise ValueError("time_func is required — must be bound to core.Clock().getTime")
        # Compute clock offset once so threads use perf_counter without GIL contention
        self._clock_offset = time_func() - time.perf_counter()
        if not HAS_SERIAL:
            raise RuntimeError(
                f"pyserial not installed — cannot open port {self.port}"
            )

        last_err = None
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self._serial = serial.Serial(
                    port=self.port, baudrate=self.baudrate,
                    timeout=self.timeout, write_timeout=0.1,
                )
                self._serial.reset_input_buffer()
                self._running = True
                self._rx_buf = ""
                threading.Thread(target=self._reader_loop, daemon=True).start()
                threading.Thread(target=self._writer_loop, daemon=True).start()
                return
            except Exception as e:
                last_err = e
                self._serial = None
                if attempt < max_retries - 1:
                    time.sleep(0.5)

        raise RuntimeError(
            f"Failed to open serial port {self.port} after {max_retries} attempts: {last_err}"
        )

    def _reader_loop(self):
        error_count = 0
        rx_buf = self._rx_buf
        while self._running:
            # Check flush signal from another thread
            if self._flush_event.is_set():
                rx_buf = ""
                self._flush_event.clear()
            try:
                if not self._serial or not getattr(self._serial, "is_open", False):
                    break

                n = self._serial.in_waiting
                if n == 0:
                    time.sleep(0.001)
                    continue

                raw = self._serial.read(n)
                if not raw:
                    continue

                t_sys = time.perf_counter() + self._clock_offset
                rx_buf += raw.decode("ascii", errors="ignore")

                # Split on newline boundaries; keep incomplete tail in buffer
                while "\n" in rx_buf:
                    line, rx_buf = rx_buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        try:
                            self.data_queue.put_nowait((t_sys, line))
                        except queue.Full:
                            try:
                                self.data_queue.get_nowait()
                                self.data_queue.put_nowait((t_sys, line))
                            except Exception:
                                pass
                error_count = 0
            except Exception:
                if not self._running:
                    break
                error_count += 1
                time.sleep(0.01)
                if error_count > 100:
                    self._running = False
                    break
        self._rx_buf = rx_buf

    def _writer_loop(self):
        while self._running:
            try:
                cmd = self.tx_queue.get(timeout=0.01)
            except queue.Empty:
                continue
            try:
                if self._serial and getattr(self._serial, "is_open", False):
                    if isinstance(cmd, bytes):
                        self._serial.write(cmd)
                    else:
                        self._serial.write(cmd.encode("ascii"))
            except Exception:
                pass

    def send_command(self, cmd: Union[str, bytes]):
        try:
            self.tx_queue.put_nowait(cmd)
        except queue.Full:
            pass

    def drain_queue(self) -> List[Tuple[float, str]]:
        items = []
        while not self.data_queue.empty():
            try:
                items.append(self.data_queue.get_nowait())
            except queue.Empty:
                break
        return items

    def flush_input(self):
        """Discard all buffered serial data and pending queue items."""
        # Signal reader thread to clear its local rx_buf
        self._flush_event.set()
        if self._serial and getattr(self._serial, "is_open", False):
            self._serial.reset_input_buffer()
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

    def is_alive(self) -> bool:
        return self._running

    def stop(self):
        self._running = False
        time.sleep(self.timeout + 0.05)
        # Drain pending TX commands
        while not self.tx_queue.empty():
            try:
                self.tx_queue.get_nowait()
            except queue.Empty:
                break
        if self._serial and getattr(self._serial, "is_open", False):
            self._serial.close()


class MockSerialDaemon:
    def __init__(self):
        self.data_queue = queue.Queue(maxsize=8192)
        self._running = False
        self._clock_offset: float = 0.0
        self._mock_generator = None

    def start(self, time_func: Callable[[], float], mock_generator: Callable[[int], str] = None):
        if time_func is None:
            raise ValueError("time_func is required — must be bound to core.Clock().getTime")
        self._clock_offset = time_func() - time.perf_counter()
        self._mock_generator = mock_generator
        self._running = True
        threading.Thread(target=self._mock_loop, daemon=True).start()

    def _mock_loop(self):
        t_ard = 0
        period = 0.01
        next_tick = time.perf_counter() + period
        while self._running:
            t_sys = time.perf_counter() + self._clock_offset
            t_ard += 10
            if self._mock_generator:
                raw = self._mock_generator(t_ard)
            else:
                raw = f"{t_ard},0,0,0,0"
            try:
                self.data_queue.put_nowait((t_sys, raw))
            except queue.Full:
                pass
            time.sleep(max(0, next_tick - time.perf_counter()))
            next_tick += period

    def send_command(self, cmd: Union[str, bytes]):
        pass

    def drain_queue(self) -> List[Tuple]:
        items = []
        while not self.data_queue.empty():
            try:
                items.append(self.data_queue.get_nowait())
            except queue.Empty:
                break
        return items

    def flush_input(self):
            """丢弃模拟队列中尚未处理的数据"""
            while not self.data_queue.empty():
                try:
                    self.data_queue.get_nowait()
                except queue.Empty:
                    break

    def is_alive(self) -> bool:
        return self._running

    def stop(self):
        self._running = False
