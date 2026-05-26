"""
Airflow Pump Speed Test Suite - Desktop Controller
Board: Arduino Mega 2560 | Serial: 115200
Tech: CustomTkinter | Dark Cyberpunk Theme
Protocol:
  Activate: <index,duration_ms>  or <index>
  Stop:     <S,index>
  Recv:     <ACK,idx,dur>  <DONE,idx>  <READY>  <ERR,...>
"""

import threading
import time
import re
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import serial
import serial.tools.list_ports

# ── Theme Constants ──────────────────────────────────────────────────────────
BG_DEEP         = "#0A0A0A"
BG_SURFACE      = "#141414"
BG_CARD         = "#1A1A1A"
BG_CARD_HOVER   = "#222222"
ACCENT_CYAN     = "#00E5FF"
ACCENT_CYAN_DIM = "#007A8A"
ACCENT_PURPLE   = "#B300FF"
ACCENT_GREEN    = "#00E676"
ACCENT_RED      = "#FF1744"
ACCENT_ORANGE   = "#FF9100"
TEXT_PRIMARY     = "#E0E0E0"
TEXT_SECONDARY   = "#888888"
TEXT_DIM         = "#555555"
BORDER_SUBTLE    = "#2A2A2A"

CHANNEL_COUNT    = 8
ACTIVATE_DURATION = 10000  # ms


# ── Serial Manager ───────────────────────────────────────────────────────────

class SerialManager:
    """Thread-safe serial connection manager."""

    def __init__(self):
        self.port: serial.Serial | None = None
        self.connected = False
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self.on_message: callable = None  # callback(raw_line)

    @staticmethod
    def list_ports() -> list[str]:
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port: str, baud: int = 115200) -> bool:
        with self._lock:
            if self.connected:
                return True
            try:
                self.port = serial.Serial(port, baud, timeout=0.1)
                self.connected = True
                self._running = True
                self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._reader_thread.start()
                return True
            except Exception as e:
                print(f"[Serial] Connect failed: {e}")
                return False

    def disconnect(self):
        with self._lock:
            self._running = False
            if self.port and self.port.is_open:
                self.port.close()
            self.connected = False
            self.port = None

    def send(self, msg: str):
        with self._lock:
            if self.port and self.port.is_open:
                self.port.write(msg.encode("utf-8"))

    def activate_channel(self, index: int, duration_ms: int = ACTIVATE_DURATION):
        self.send(f"<{index},{duration_ms}>")

    def stop_channel(self, index: int):
        self.send(f"<S,{index}>")

    def _read_loop(self):
        buf = ""
        while self._running:
            try:
                if self.port and self.port.in_waiting:
                    data = self.port.read(self.port.in_waiting).decode("utf-8", errors="replace")
                    buf += data
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line and self.on_message:
                            self.on_message(line)
                else:
                    time.sleep(0.02)
            except Exception:
                if self._running:
                    self.connected = False
                break


# ── Pump Card Widget ─────────────────────────────────────────────────────────

class PumpCard(ctk.CTkFrame):
    """A single pump control card with countdown and stop capability."""

    def __init__(self, master, index: int, on_activate: callable,
                 on_stop: callable, **kwargs):
        super().__init__(master, corner_radius=12, fg_color=BG_CARD,
                         border_width=1, border_color=BORDER_SUBTLE, **kwargs)
        self.index = index
        self.on_activate = on_activate
        self.on_stop = on_stop
        self._active = False
        self._countdown_id = None
        self._remaining = 0

        self.configure(width=160, height=140)

        # Channel label
        self._lbl_channel = ctk.CTkLabel(
            self, text=f"CH {index}", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_SECONDARY, anchor="w"
        )
        self._lbl_channel.pack(anchor="w", padx=14, pady=(12, 0))

        # Status indicator
        self._indicator = ctk.CTkLabel(
            self, text="IDLE", font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_DIM
        )
        self._indicator.pack(anchor="w", padx=14, pady=(2, 0))

        # Main action button
        self._btn = ctk.CTkButton(
            self, text="ACTIVATE", height=36, corner_radius=8,
            fg_color=ACCENT_CYAN, hover_color="#00B8D4",
            text_color=BG_DEEP, font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_click
        )
        self._btn.pack(fill="x", padx=14, pady=(8, 12), side="bottom")

        # Countdown label (hidden by default)
        self._lbl_countdown = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT_CYAN
        )

        # Hover effect
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _):
        if not self._active:
            self.configure(fg_color=BG_CARD_HOVER, border_color=ACCENT_CYAN_DIM)

    def _on_leave(self, _):
        if not self._active:
            self.configure(fg_color=BG_CARD, border_color=BORDER_SUBTLE)

    def _on_click(self):
        if self._active:
            self.on_stop(self.index)
        else:
            self.on_activate(self.index)

    def activate(self):
        """Switch to active / countdown state (button becomes STOP)."""
        if self._active:
            return
        self._active = True
        self._remaining = ACTIVATE_DURATION // 1000

        self.configure(fg_color="#0D1B2A", border_color=ACCENT_CYAN)
        self._indicator.configure(text="ACTIVE", text_color=ACCENT_GREEN)

        # Button -> STOP
        self._btn.configure(
            text="STOP", state="normal",
            fg_color=ACCENT_RED, hover_color="#D50000",
            text_color="#FFFFFF"
        )

        self._lbl_countdown.pack(anchor="center", pady=(0, 4))
        self._tick()

    def _tick(self):
        if not self._active:
            return
        self._lbl_countdown.configure(text=f"{self._remaining}s")
        if self._remaining <= 0:
            self._deactivate()
            return
        self._remaining -= 1
        self._countdown_id = self.after(1000, self._tick)

    def _deactivate(self):
        """Natural countdown expiry -> return to IDLE."""
        self._active = False
        self._countdown_id = None
        self._lbl_countdown.pack_forget()
        self.configure(fg_color=BG_CARD, border_color=BORDER_SUBTLE)
        self._indicator.configure(text="IDLE", text_color=TEXT_DIM)
        self._btn.configure(
            text="ACTIVATE", state="normal",
            fg_color=ACCENT_CYAN, hover_color="#00B8D4",
            text_color=BG_DEEP
        )

    def force_deactivate(self):
        """External reset (stop command / disconnect / <DONE> from firmware)."""
        if self._countdown_id:
            self.after_cancel(self._countdown_id)
            self._countdown_id = None
        self._active = False
        self._lbl_countdown.pack_forget()
        self.configure(fg_color=BG_CARD, border_color=BORDER_SUBTLE)
        self._indicator.configure(text="IDLE", text_color=TEXT_DIM)
        self._btn.configure(
            text="ACTIVATE", state="normal",
            fg_color=ACCENT_CYAN, hover_color="#00B8D4",
            text_color=BG_DEEP
        )

    @property
    def is_active(self) -> bool:
        return self._active


# ── Main Application ─────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window setup
        self.title("Airflow Pump Test Suite")
        self.geometry("720x620")
        self.minsize(640, 560)
        self.configure(fg_color=BG_DEEP)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.serial_mgr = SerialManager()
        self.serial_mgr.on_message = self._on_serial_message

        self._build_ui()
        self._refresh_ports()

    # ── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self):
        # Top Bar
        top = ctk.CTkFrame(self, fg_color=BG_SURFACE, corner_radius=0, height=60)
        top.pack(fill="x")
        top.pack_propagate(False)

        ctk.CTkLabel(top, text="AIRFLOW PUMP TEST SUITE",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=ACCENT_CYAN).pack(side="left", padx=20)

        # Serial controls (right side of top bar)
        serial_frame = ctk.CTkFrame(top, fg_color="transparent")
        serial_frame.pack(side="right", padx=16, pady=10)

        self._port_var = ctk.StringVar()
        self._port_menu = ctk.CTkOptionMenu(
            serial_frame, variable=self._port_var, values=["(no ports)"],
            width=140, fg_color=BG_CARD, button_color=BG_CARD_HOVER,
            button_hover_color=ACCENT_CYAN_DIM, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=ACCENT_CYAN_DIM
        )
        self._port_menu.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            serial_frame, text="Refresh", width=64, height=30,
            fg_color=BG_CARD, hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=11), command=self._refresh_ports
        ).pack(side="left", padx=(0, 6))

        self._btn_connect = ctk.CTkButton(
            serial_frame, text="Connect", width=80, height=30,
            fg_color=ACCENT_CYAN, hover_color="#00B8D4",
            text_color=BG_DEEP, font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_connection
        )
        self._btn_connect.pack(side="left")

        # Status indicator
        self._lbl_status = ctk.CTkLabel(
            serial_frame, text="Disconnected", font=ctk.CTkFont(size=10),
            text_color=ACCENT_RED
        )
        self._lbl_status.pack(side="left", padx=(10, 0))

        # Pump Grid (main area)
        grid_frame = ctk.CTkFrame(self, fg_color=BG_DEEP)
        grid_frame.pack(fill="both", expand=True, padx=20, pady=(16, 8))

        for col in range(4):
            grid_frame.columnconfigure(col, weight=1, uniform="col")
        for row in range(2):
            grid_frame.rowconfigure(row, weight=1, uniform="row")

        self.pump_cards: list[PumpCard] = []
        for i in range(CHANNEL_COUNT):
            row, col = divmod(i, 4)
            card = PumpCard(
                grid_frame, index=i,
                on_activate=self._activate_pump,
                on_stop=self._stop_pump
            )
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            self.pump_cards.append(card)

        # Bottom: Activate/Stop All + Log
        bottom = ctk.CTkFrame(self, fg_color=BG_SURFACE, corner_radius=0, height=42)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)

        self._btn_all = ctk.CTkButton(
            bottom, text="ACTIVATE ALL", height=30, corner_radius=8,
            fg_color=ACCENT_PURPLE, hover_color="#8B00CC",
            text_color="#FFFFFF", font=ctk.CTkFont(size=12, weight="bold"),
            command=self._toggle_all
        )
        self._btn_all.pack(side="left", padx=16, pady=6)

        # Log area
        self._log = ctk.CTkTextbox(
            bottom, height=30, fg_color=BG_DEEP, text_color=TEXT_SECONDARY,
            font=ctk.CTkFont(family="Consolas", size=10), border_width=0
        )
        self._log.pack(fill="x", expand=True, padx=(0, 16), pady=6)
        self._log.configure(state="disabled")

    # ── Serial Port Management ───────────────────────────────────────────

    def _refresh_ports(self):
        ports = SerialManager.list_ports()
        if ports:
            self._port_menu.configure(values=ports)
            self._port_var.set(ports[0])
        else:
            self._port_menu.configure(values=["(no ports)"])
            self._port_var.set("(no ports)")

    def _toggle_connection(self):
        if self.serial_mgr.connected:
            self.serial_mgr.disconnect()
            self._btn_connect.configure(text="Connect", fg_color=ACCENT_CYAN)
            self._lbl_status.configure(text="Disconnected", text_color=ACCENT_RED)
            self._log_event("Serial disconnected")
            for card in self.pump_cards:
                card.force_deactivate()
            self._sync_all_button()
        else:
            port = self._port_var.get()
            if port == "(no ports)":
                messagebox.showwarning("No Port", "No serial ports detected.")
                return
            if self.serial_mgr.connect(port):
                self._btn_connect.configure(text="Disconnect", fg_color=ACCENT_RED)
                self._lbl_status.configure(text=f"Connected: {port}", text_color=ACCENT_GREEN)
                self._log_event(f"Connected to {port}")
            else:
                messagebox.showerror("Error", f"Failed to connect to {port}")

    # ── Pump Activation / Stop ───────────────────────────────────────────

    def _activate_pump(self, index: int):
        if not self.serial_mgr.connected:
            messagebox.showwarning("Not Connected", "Connect to a serial port first.")
            return
        self.serial_mgr.activate_channel(index)
        self.pump_cards[index].activate()
        self._log_event(f"CH {index} activated ({ACTIVATE_DURATION}ms)")
        self._sync_all_button()

    def _stop_pump(self, index: int):
        if not self.serial_mgr.connected:
            return
        self.serial_mgr.stop_channel(index)
        self.pump_cards[index].force_deactivate()
        self._log_event(f"CH {index} stopped")
        self._sync_all_button()

    def _toggle_all(self):
        if not self.serial_mgr.connected:
            messagebox.showwarning("Not Connected", "Connect to a serial port first.")
            return
        if any(c.is_active for c in self.pump_cards):
            self._stop_all()
        else:
            self._activate_all()

    def _activate_all(self):
        for i in range(CHANNEL_COUNT):
            self.serial_mgr.activate_channel(i)
            self.pump_cards[i].activate()
        self._log_event(f"All channels activated ({ACTIVATE_DURATION}ms)")
        self._sync_all_button()

    def _stop_all(self):
        for i in range(CHANNEL_COUNT):
            if self.pump_cards[i].is_active:
                self.serial_mgr.stop_channel(i)
                self.pump_cards[i].force_deactivate()
        self._log_event("All channels stopped")
        self._sync_all_button()

    def _sync_all_button(self):
        """Update bottom button label based on whether any channel is active."""
        if any(c.is_active for c in self.pump_cards):
            self._btn_all.configure(
                text="STOP ALL", fg_color=ACCENT_RED,
                hover_color="#D50000"
            )
        else:
            self._btn_all.configure(
                text="ACTIVATE ALL", fg_color=ACCENT_PURPLE,
                hover_color="#8B00CC"
            )

    # ── Serial Message Handling ──────────────────────────────────────────

    def _on_serial_message(self, line: str):
        """Called from serial reader thread — schedule on main thread."""
        self.after(0, self._handle_message, line)

    def _handle_message(self, line: str):
        self._log_event(f"RX: {line}")
        # Parse <DONE,index> to force-deactivate card
        m = re.match(r"<DONE,(\d+)>", line)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < CHANNEL_COUNT:
                self.pump_cards[idx].force_deactivate()
                self._sync_all_button()

    # ── Logging ──────────────────────────────────────────────────────────

    def _log_event(self, text: str):
        self._log.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self._log.insert("end", f"[{ts}] {text}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    # ── Cleanup ──────────────────────────────────────────────────────────

    def destroy(self):
        self.serial_mgr.disconnect()
        super().destroy()


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
