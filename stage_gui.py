"""Simple absolute-position GUI for the PI C-863 / M-112.1DG stage.

Run from the EIS project directory: uv run python stage_gui.py
Requires pipython (already listed in the project's pyproject.toml).

IMPORTANT: Referencing (homing) moves the stage. Ensure the travel path is clear.
Do not run this GUI and the EIS experiment runner on the same serial port.
"""
from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from pipython import GCSDevice, pitools

CONTROLLER = "C-863"
STAGE_MODEL = "M-112.1DG"
REFERENCE_MODE = "FNL"
DEFAULT_PORT = "3"
BAUDRATE = 115200


class StageGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PI Stage — Position Control")
        self.geometry("430x270")
        self.resizable(False, False)
        self.device = None
        self.axis = None
        self.referenced = False
        self.busy = False
        self.messages = queue.Queue()
        self.port = tk.StringVar(value=DEFAULT_PORT)
        self.target = tk.StringVar(value="0.0")
        self.position = tk.StringVar(value="Not connected")
        self.status = tk.StringVar(value="Disconnected")

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Stage position control", font=("TkDefaultFont", 14, "bold")).pack(anchor="w", pady=(0, 12))

        connection = ttk.Frame(frame)
        connection.pack(fill="x", pady=(0, 12))
        ttk.Label(connection, text="COM port:").pack(side="left")
        ttk.Entry(connection, textvariable=self.port, width=7).pack(side="left", padx=8)
        self.connect_button = ttk.Button(connection, text="Connect", command=self.connect)
        self.connect_button.pack(side="left")
        self.reference_button = ttk.Button(connection, text="Reference stage", command=self.reference)
        self.reference_button.pack(side="left", padx=(8, 0))

        ttk.Label(frame, text="Current position:").pack(anchor="w")
        ttk.Label(frame, textvariable=self.position, font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(2, 12))
        entry_row = ttk.Frame(frame)
        entry_row.pack(fill="x")
        ttk.Label(entry_row, text="Target position (mm):").pack(side="left")
        entry = ttk.Entry(entry_row, textvariable=self.target, width=13)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _event: self.move())
        self.move_button = ttk.Button(entry_row, text="Move", command=self.move)
        self.move_button.pack(side="left")
        ttk.Separator(frame).pack(fill="x", pady=12)
        ttk.Label(frame, textvariable=self.status, wraplength=390).pack(anchor="w")
        self._update_buttons()
        self.after(75, self._drain_messages)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _update_buttons(self):
        connected = self.device is not None
        self.connect_button.configure(state="disabled" if self.busy or connected else "normal")
        self.reference_button.configure(state="normal" if connected and not self.busy else "disabled")
        self.move_button.configure(state="normal" if connected and self.referenced and not self.busy else "disabled")

    def _run(self, task, description):
        if self.busy:
            return
        self.busy = True
        self.status.set(description)
        self._update_buttons()

        def worker():
            try:
                task()
                self.messages.put(("success", description))
            except Exception as exc:
                self.messages.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def connect(self):
        try:
            port = int(self.port.get().strip().upper().removeprefix("COM"))
            if port <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid port", "Enter a COM port number, e.g. 3 or COM3.")
            return

        def task():
            device = GCSDevice(CONTROLLER)
            try:
                device.ConnectRS232(comport=port, baudrate=BAUDRATE)
                axis = device.axes[0]
            except Exception:
                device.CloseConnection()
                raise
            self.device = device
            self.axis = axis
            self.referenced = False
            self.messages.put(("position", self._read_position()))

        self._run(task, "Connecting to stage...")

    def _read_position(self):
        return float(self.device.qPOS(self.axis)[self.axis])

    def reference(self):
        if self.device is None or self.busy:
            return
        if not messagebox.askyesno(
            "Reference stage",
            "Referencing with FNL will physically move the stage toward its limit.\n\n"
            "Ensure the path is clear and the setup cannot collide. Continue?",
        ):
            return

        def task():
            self.referenced = False
            pitools.startup(self.device, stages=[STAGE_MODEL], refmodes=[REFERENCE_MODE])
            self.referenced = True
            self.messages.put(("position", self._read_position()))

        self._run(task, "Referencing stage (stage will move)...")

    def move(self):
        if self.device is None or not self.referenced or self.busy:
            return
        try:
            target = float(self.target.get().strip())
            if not math.isfinite(target):
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid position", "Enter a finite numeric position in mm.")
            return

        def task():
            # The controller enforces its configured travel limits.
            # Do not bypass its limits or reference requirement.
            self.device.MOV(self.axis, target)
            pitools.waitontarget(self.device, axes=self.axis)
            self.messages.put(("position", self._read_position()))

        self._run(task, f"Moving to {target:g} mm...")

    def _drain_messages(self):
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == "position":
                    self.position.set(f"{value:.4f} mm")
                elif kind == "success":
                    self.busy = False
                    self.status.set("Ready" if self.referenced else "Connected — reference stage before moving")
                    self._update_buttons()
                elif kind == "error":
                    self.busy = False
                    self.status.set(f"Error: {value}")
                    self._update_buttons()
                    messagebox.showerror("Stage error", value)
        except queue.Empty:
            pass
        self.after(75, self._drain_messages)

    def close(self):
        if self.busy:
            messagebox.showwarning("Stage busy", "Wait for the current operation to finish before closing.")
            return
        if self.device is not None:
            try:
                self.device.CloseConnection()
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    StageGUI().mainloop()
