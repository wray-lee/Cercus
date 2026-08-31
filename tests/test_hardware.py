"""Tests for KinematicsParser, SerialDaemon, and MockSerialDaemon.

Seam: KinematicsParser.parse / get_telemetry / _apply_calibration, SerialDaemon, MockSerialDaemon
"""
import queue
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

import src.core.hardware as hw_mod
from src.core.hardware import KinematicsParser, MockSerialDaemon, SerialDaemon


def _make_parser():
    return KinematicsParser()


def test_parse_returns_calibrated_row() -> None:
    p = _make_parser()
    row = p.parse(1.0, "100,5,3,2,1", 1)
    assert row is not None
    # row: [sys_time_str, ard_time, dx, dy, dz, stim_state, g_id]
    assert len(row) == 7
    assert row[-1] == 1  # global_trial_id


def test_parse_empty_returns_none() -> None:
    p = _make_parser()
    assert p.parse(1.0, "", 1) is None
    assert p.parse(1.0, "  ", 1) is None


def test_single_pass_no_double_accumulation() -> None:
    """B1/B2: Calling parse() once must not double-accumulate.
    With jitter_thresh=0, accum should reset after each emit.
    Parse two samples and verify dx values are independent."""
    p = _make_parser()
    row1 = p.parse(1.0, "100,10,0,0,0", 1)
    row2 = p.parse(2.0, "200,10,0,0,0", 2)
    # With identity matrix and thresh=0, each sample should produce dx=10
    assert row1 is not None
    assert row2 is not None
    # dx is at index 1 (after sys_time at 0)
    assert float(row1[1+1]) == 10.0  # field index 1 = dx
    assert float(row2[1+1]) == 10.0  # not 20 (which would mean double-accumulation)


def test_get_telemetry_returns_dict() -> None:
    p = _make_parser()
    tel = p.get_telemetry("100,5,3,2,1")
    assert isinstance(tel, dict)
    assert "dx" in tel
    assert "dy" in tel
    assert "dz" in tel


def test_parse_and_get_telemetry_both_mutate_accumulator() -> None:
    """Verify that calling parse() then get_telemetry() on the same data
    double-counts — this is the bug we fixed by NOT doing both."""
    p = _make_parser()
    # First: parse (accumulates dx=10 then emits)
    p.parse(1.0, "100,10,0,0,0", 1)
    # Second: get_telemetry on same data (would accumulate again!)
    tel = p.get_telemetry("100,10,0,0,0")
    # With thresh=0 and identity matrix, this second call also emits 10
    # But the accumulator was already drained by parse(), so this is
    # a fresh accumulation — the issue was that BOTH were called in
    # _drain_hardware, meaning kinematic engine got 2x the displacement.
    assert float(tel["dx"]) == 10.0


def test_idx_map_precomputed() -> None:
    """M3: idx_map should be precomputed in __init__, not per-call."""
    p = _make_parser()
    assert hasattr(p, '_idx_map')
    assert 'dx' in p._idx_map
    assert 'dy' in p._idx_map
    assert 'dz' in p._idx_map


def test_out_buf_precomputed() -> None:
    """M3: _out_buf should exist for zero-allocation reuse."""
    p = _make_parser()
    assert hasattr(p, '_out_buf')
    assert len(p._out_buf) == len(p._field_defs)


def test_field_keys_property() -> None:
    """field_keys should be a public tuple matching _field_defs keys."""
    p = _make_parser()
    assert isinstance(p.field_keys, tuple)
    assert p.field_keys == ('ard_time', 'dx', 'dy', 'dz', 'stim_state')


def test_calibration_matrix_applied() -> None:
    """Verify calibration matrix transforms displacements."""
    p = _make_parser()
    # Swap dx and dy via matrix
    p.set_calib_matrix([[0, 1, 0], [1, 0, 0], [0, 0, 1]])
    tel = p.get_telemetry("100,10,20,0,0")
    assert float(tel["dx"]) == 20.0  # was dy
    assert float(tel["dy"]) == 10.0  # was dx


def test_parser_headers_and_safe_int() -> None:
    """Verify get_headers and _safe_int error handling."""
    p = _make_parser()
    headers = p.get_headers()
    assert headers == ["sys_time", "ard_time", "dx", "dy", "dz", "stim_state", "global_trial_id"]

    assert KinematicsParser._safe_int("123") == 123
    assert KinematicsParser._safe_int("abc") is None
    assert KinematicsParser._safe_int(None) is None  # type: ignore


def test_parser_missing_fields_and_invalid_values() -> None:
    """Verify _parse_fields handles short lines and invalid integers."""
    p = _make_parser()
    # Short line (only 2 parts, schema expects 5) -> fills with default values
    row = p.parse(1.0, "100,5", 1)
    assert row is not None
    assert len(row) == 7
    assert row[1] == 100
    assert row[2] == 5
    assert row[3] == 0  # dy default
    assert row[4] == 0  # dz default
    assert row[5] == 0  # stim_state default

    # Invalid integer in line -> returns None
    assert p.parse(1.0, "100,abc,0,0,0", 1) is None
    assert p.get_telemetry("100,abc,0,0,0") is None


def test_parser_legacy_calib_factors() -> None:
    """Verify non-spatial scalar calibration factors application."""
    schema = [
        (0, 0, "ard_time"),
        (1, 0, "dx"),
        (2, 0, "dy"),
        (3, 0, "dz"),
        (4, 0, "stim_state"),
        (5, 0, "aux_sensor"),
    ]
    p = KinematicsParser(telemetry_schema=schema, calib_factors={"aux_sensor": 2.5})
    p.set_calib_factors({"stim_state": 1.0, "aux_sensor": 3.0})
    row = p.parse(1.0, "100,10,20,30,1,10", 1)
    assert row is not None
    # aux_sensor at index 5 in fields (6 in row) should be scaled by 3.0
    assert row[6] == 30.0


def test_parser_spatial_jitter_threshold() -> None:
    """Verify spatial hysteresis accumulator when jitter threshold is active."""
    p = _make_parser()
    p._jitter_thresh = 5.0

    # Under threshold (dx=3.0 < 5.0) -> output dx=0.0, accum=3.0
    row1 = p.parse(1.0, "100,3,0,0,0", 1)
    assert row1 is not None
    assert row1[2] == 0.0

    # Accumulates next frame (dx=3.0 + 3.0 = 6.0 >= 5.0) -> output dx=6.0, accum resets
    row2 = p.parse(2.0, "200,3,0,0,0", 1)
    assert row2 is not None
    assert row2[2] == 6.0

    # Next frame under threshold (dx=2.0) -> output dx=0.0
    row3 = p.parse(3.0, "300,2,0,0,0", 1)
    assert row3 is not None
    assert row3[2] == 0.0


def test_mock_serial_daemon_lifecycle() -> None:
    """Verify MockSerialDaemon full lifecycle and generator customization."""
    daemon = MockSerialDaemon()
    assert daemon.is_alive() is False

    # Starting without time_func raises ValueError
    with pytest.raises(ValueError, match="time_func is required"):
        daemon.start(time_func=None)  # type: ignore

    # Start with custom mock generator
    def _custom_gen(t_ard: int) -> str:
        return f"{t_ard},10,20,30,0"

    daemon.start(time_func=time.perf_counter, mock_generator=_custom_gen)
    assert daemon.is_alive() is True

    # Allow some data to accumulate
    time.sleep(0.03)
    items = daemon.drain_queue()
    assert len(items) > 0
    assert "10,20,30,0" in items[0][1]

    # Test send_command (no-op)
    daemon.send_command("PING")

    # Test flush_input
    time.sleep(0.02)
    daemon.flush_input()
    assert daemon.data_queue.empty()

    # Test stop and thread join
    daemon.stop()
    assert daemon.is_alive() is False
    assert daemon._mock_thread is not None
    assert not daemon._mock_thread.is_alive()


def test_serial_daemon_start_exceptions() -> None:
    """Verify SerialDaemon start validation and failure handling."""
    sd = SerialDaemon("COM1")

    # 1. time_func is None
    with pytest.raises(ValueError, match="time_func is required"):
        sd.start(time_func=None)  # type: ignore

    # 2. HAS_SERIAL is False
    with patch.object(hw_mod, "HAS_SERIAL", False):
        with pytest.raises(RuntimeError, match="pyserial not installed"):
            sd.start(time_func=time.perf_counter)

    # 3. Serial open retry failure
    mock_serial_mod = MagicMock()
    mock_serial_mod.Serial.side_effect = Exception("Port busy")
    with patch.object(hw_mod, "HAS_SERIAL", True):
        with patch.object(hw_mod, "serial", mock_serial_mod):
            with patch("time.sleep", return_value=None):
                with pytest.raises(RuntimeError, match="Failed to open serial port"):
                    sd.start(time_func=time.perf_counter)


class FakeSerialPort:
    """Simulated Serial port for SerialDaemon tests."""

    def __init__(self, read_data: bytes = b"") -> None:
        self.is_open = True
        self.rx_bytes = bytearray(read_data)
        self.written_bytes = bytearray()
        self.write_timeout = 0.1

    @property
    def in_waiting(self) -> int:
        return len(self.rx_bytes)

    def read(self, n: int) -> bytes:
        chunk = bytes(self.rx_bytes[:n])
        del self.rx_bytes[:n]
        return chunk

    def write(self, data: bytes) -> int:
        self.written_bytes.extend(data)
        return len(data)

    def reset_input_buffer(self) -> None:
        self.rx_bytes.clear()

    def close(self) -> None:
        self.is_open = False


def test_serial_daemon_thread_cleanup_and_data_flow() -> None:
    """Verify SerialDaemon reader and writer thread lifecycle and cleanup."""
    fake_port = FakeSerialPort()
    sd = SerialDaemon("COM99", timeout=0.01)

    mock_serial_mod = MagicMock()
    mock_serial_mod.Serial.return_value = fake_port

    with patch.object(hw_mod, "HAS_SERIAL", True):
        with patch.object(hw_mod, "serial", mock_serial_mod):
            sd.start(time_func=time.perf_counter)

    assert sd.is_alive() is True
    assert sd._reader_thread is not None and sd._reader_thread.is_alive()
    assert sd._writer_thread is not None and sd._writer_thread.is_alive()

    # Append data after start() has reset input buffer
    fake_port.rx_bytes.extend(b"100,1,2,3,0\n200,4,5,6,0\n")

    # Wait for reader to process lines into data_queue
    time.sleep(0.04)
    items = sd.drain_queue()
    assert len(items) == 2
    assert "100,1,2,3,0" in items[0][1]
    assert "200,4,5,6,0" in items[1][1]

    # Test send_command with str and bytes
    sd.send_command("INIT\n")
    sd.send_command(b"PULSE\n")
    time.sleep(0.04)
    assert b"INIT\n" in fake_port.written_bytes
    assert b"PULSE\n" in fake_port.written_bytes

    # Test flush_input
    fake_port.rx_bytes.extend(b"999,0,0,0,0\n")
    sd.flush_input()
    time.sleep(0.01)
    assert len(sd.drain_queue()) == 0

    # Test stop and verify complete thread cleanup
    reader_ref = sd._reader_thread
    writer_ref = sd._writer_thread

    # Put a pending TX command before stop to test draining
    sd.tx_queue.put_nowait("REMAINING")

    sd.stop()
    assert sd.is_alive() is False
    assert fake_port.is_open is False

    # Verify both threads joined and died
    assert not reader_ref.is_alive()
    assert not writer_ref.is_alive()
    assert sd.tx_queue.empty()


def test_serial_daemon_reader_queue_full_and_error_recovery() -> None:
    """Verify reader loop handles full queue and recovers from serial exceptions."""
    fake_port = FakeSerialPort()
    sd = SerialDaemon("COM99", timeout=0.01)
    # Set a tiny data_queue to test queue.Full handling
    sd.data_queue = queue.Queue(maxsize=2)

    mock_serial_mod = MagicMock()
    mock_serial_mod.Serial.return_value = fake_port

    with patch.object(hw_mod, "HAS_SERIAL", True):
        with patch.object(hw_mod, "serial", mock_serial_mod):
            sd.start(time_func=time.perf_counter)

    # Feed 4 lines into queue with maxsize=2
    fake_port.rx_bytes.extend(b"1,0,0,0,0\n2,0,0,0,0\n3,0,0,0,0\n4,0,0,0,0\n")
    time.sleep(0.04)

    items = sd.drain_queue()
    assert len(items) == 2
    # Oldest items were dropped to make room for newest
    assert "3,0,0,0,0" in items[0][1]
    assert "4,0,0,0,0" in items[1][1]

    # Test read returning empty bytes
    fake_port.rx_bytes.clear()
    time.sleep(0.02)

    # Test consecutive read errors causing loop exit when error_count > 100
    fake_port.read = MagicMock(side_effect=Exception("Read failure"))  # type: ignore
    time.sleep(0.05)

    sd.stop()
    assert not sd._reader_thread.is_alive()


def test_mock_serial_daemon_default_generator_and_queue_full() -> None:
    """Verify MockSerialDaemon default format and queue.Full handling."""
    daemon = MockSerialDaemon()
    daemon.data_queue = queue.Queue(maxsize=2)
    daemon.start(time_func=time.perf_counter)  # mock_generator is None -> uses default format
    time.sleep(0.05)
    items = daemon.drain_queue()
    assert len(items) == 2
    assert ",0,0,0,0" in items[0][1]
    daemon.stop()


def test_serial_daemon_edge_cases() -> None:
    """Verify send_command queue full, write error handling, and get_telemetry edge cases."""
    p = _make_parser()
    assert p.get_telemetry("") is None
    assert p.get_telemetry("   ") is None

    fake_port = FakeSerialPort()
    sd = SerialDaemon("COM99", timeout=0.01)
    # Set tx_queue to maxsize=1
    sd.tx_queue = queue.Queue(maxsize=1)
    sd.send_command("CMD1")
    # Queue is full, should not raise
    sd.send_command("CMD2")

    # Test writer error handling
    fake_port.write = MagicMock(side_effect=Exception("Write failed"))  # type: ignore
    mock_serial_mod = MagicMock()
    mock_serial_mod.Serial.return_value = fake_port

    with patch.object(hw_mod, "HAS_SERIAL", True):
        with patch.object(hw_mod, "serial", mock_serial_mod):
            sd.start(time_func=time.perf_counter)


    time.sleep(0.03)
    sd.stop()




