"""Tkinter front end for the existing frequency-sweep main.py.

Place this file beside main.py, meter.py and saver.py, then run:
    uv run python experiment_gui.py

The GUI runs main.py as a subprocess; main.py remains unchanged.
"""

import json
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

HERE = Path(__file__).resolve().parent
SETTINGS_PATH = HERE / ".experiment_gui_settings.json"
DEFAULTS = {
    "script": str(HERE / "main.py"),
    "port": "COM3", "baudrate": "115200", "save": "",
    "level": "0.05", "bias": "0.0", "average": "1",
    "freq_from": "10", "freq_to": "200000", "count": "7",
    "mode": "STA", "positions": "0.1 0.2", "stage": "3",
    "plot": False, "show_plots": False,
    "Device": "", "Experiment Start": "", "Experiment End": "",
    "Experiment Number": "", "Notes": "",
    "Agarose concentration": "", "Agarose doping concentration": "",
    "Solution": "",
}
METADATA_FIELDS = [
    "Device", "Experiment Start", "Experiment End", "Experiment Number",
    "Notes", "Agarose concentration", "Agarose doping concentration", "Solution",
]
PARAMETERS = [
    ("Meter serial port", "port"), ("Meter baudrate", "baudrate"),
    ("Stimulus level (V)", "level"),
    ("Bias voltages (V; space/comma separated)", "bias"),
    ("Samples to average", "average"), ("Start frequency (Hz)", "freq_from"),
    ("End frequency (Hz)", "freq_to"), ("Frequencies per decade", "count"),
    ("Measurement mode", "mode"),
    ("Stage positions (mm; space/comma separated)", "positions"),
    ("Stage COM port number", "stage"),
]


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def numbers(raw, label):
    values = raw.replace(",", " ").split()
    if not values:
        raise ValueError(f"Enter at least one value for {label}.")
    for item in values:
        float(item)
    return values


class ExperimentGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LCR 6200 / PI Stage — Experiment Runner")
        self.geometry("990x760")
        self.minsize(820, 570)
        saved = self.load_settings()
        self.vars = {k: tk.StringVar(value=saved.get(k, v)) for k, v in DEFAULTS.items() if k not in ("plot", "show_plots")}
        self.plot_enabled = tk.BooleanVar(value=saved.get("plot", False))
        self.show_plots = tk.BooleanVar(value=saved.get("show_plots", False))
        self.plot_windows = {}
        self.plot_seen = set()
        self.plot_pending = {}
        self.plot_directory = None
        # Notes must be newly entered for every experiment.
        self.vars["Notes"].set("")
        self.vars["save"].set("")
        self.next_number = max(1, int(saved.get("next_experiment_number", 1)))
        self.update_experiment_identity()
        self.events = queue.Queue()
        self.running = False
        self.process = None
        self.experiment_dir = None
        self.start_time = None
        self.build_ui()
        self.after(100, self.drain_events)
        self.after(700, self.poll_plots)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    @staticmethod
    def load_settings():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        # Do not reuse old run timestamps as metadata for a new experiment.
        data = {key: var.get() for key, var in self.vars.items()}
        data["plot"] = self.plot_enabled.get()
        data["show_plots"] = self.show_plots.get()
        data["Notes"] = ""  # Never restore notes for a new experiment.
        data["save"] = ""  # Name is generated, not user-entered.
        data["next_experiment_number"] = self.next_number
        data["Experiment Start"] = ""
        data["Experiment End"] = ""
        SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def update_experiment_identity(self):
        """Pick the next unused experiment### name, considering existing output folders."""
        script = Path(self.vars["script"].get().strip()).expanduser()
        base_dir = script.parent / "out" / "data"
        used = set()
        if base_dir.is_dir():
            for folder in base_dir.iterdir():
                if folder.is_dir():
                    match = re.search(r"_sweep_experiment(\d+)(?:_\d+)?$", folder.name)
                    if match:
                        used.add(int(match.group(1)))
        number = self.next_number
        while number in used:
            number += 1
        self.next_number = number
        self.vars["save"].set(f"experiment{number:03d}")
        self.vars["Experiment Number"].set(str(number))

    def build_ui(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        file_frame = ttk.LabelFrame(body, text="Main experiment script", padding=10)
        file_frame.pack(fill="x", pady=(0, 10))
        ttk.Entry(file_frame, textvariable=self.vars["script"]).pack(side="left", fill="x", expand=True)
        ttk.Button(file_frame, text="Browse…", command=self.browse_script).pack(side="left", padx=(8, 0))

       # ttk.Label(body, text="GUI version: 3-column layout • settings saved automatically on exit", foreground="#246b45").pack(anchor="w", pady=(0, 8))

        identity = ttk.Frame(body)
        identity.pack(fill="x", pady=(0, 10))
        ttk.Label(identity, text="Next experiment (automatic):").pack(side="left")
        ttk.Label(identity, textvariable=self.vars["save"], font=("TkDefaultFont", 11, "bold")).pack(side="left", padx=8)

        param_frame = ttk.LabelFrame(body, text="Measurement parameters — 3 columns", padding=10)
        param_frame.pack(fill="x", pady=(0, 10))
        for col in range(3):
            param_frame.columnconfigure(col, weight=1, uniform="parameters")
        for index, (label, key) in enumerate(PARAMETERS):
            row, col = divmod(index, 3)
            cell = ttk.Frame(param_frame, padding=(5, 4))
            cell.grid(row=row, column=col, sticky="ew")
            ttk.Label(cell, text=label, wraplength=270).pack(anchor="w")
            if key == "mode":
                widget = ttk.Combobox(cell, textvariable=self.vars[key],
                                      values=("STA", "LTA"), state="readonly", width=20)
            else:
                widget = ttk.Entry(cell, textvariable=self.vars[key], width=22)
            widget.pack(anchor="w", pady=(3, 0))

        plot_row = (len(PARAMETERS) + 2) // 3
        ttk.Checkbutton(
            param_frame,
            text="Save plots in experiment folder (--plot)",
            variable=self.plot_enabled,
            command=self.update_plot_controls,
        ).grid(row=plot_row, column=0, columnspan=2,
               sticky="w", padx=5, pady=(10, 5))
        self.show_plots_checkbox = ttk.Checkbutton(
            param_frame,
            text="Show plots in separate windows as saved",
            variable=self.show_plots,
        )
        self.show_plots_checkbox.grid(row=plot_row, column=2,
                                      sticky="w", padx=5, pady=(10, 5))
        self.update_plot_controls()

        meta_frame = ttk.LabelFrame(body, text="Experiment metadata — 3 columns", padding=10)
        meta_frame.pack(fill="x", pady=(0, 10))
        for col in range(3):
            meta_frame.columnconfigure(col, weight=1, uniform="metadata")
        # Standard metadata fields in three columns; Notes gets its own full-width row.
        compact_fields = [field for field in METADATA_FIELDS if field != "Notes"]
        for index, field in enumerate(compact_fields):
            row, col = divmod(index, 3)
            cell = ttk.Frame(meta_frame, padding=(5, 4))
            cell.grid(row=row, column=col, sticky="nsew")
            ttk.Label(cell, text=field).pack(anchor="w")
            state = "readonly" if field in (
                "Experiment Start", "Experiment End", "Experiment Number"
            ) else "normal"
            ttk.Entry(cell, textvariable=self.vars[field], state=state,
                      width=22).pack(anchor="w", pady=(3, 0))

        notes_row = (len(compact_fields) + 2) // 3
        ttk.Label(meta_frame, text="Notes (required — enter fresh notes for every run)").grid(
            row=notes_row, column=0, columnspan=3, sticky="w", padx=5, pady=(12, 3)
        )
        self.notes = tk.Text(meta_frame, height=7, wrap="word", undo=True)
        self.notes.grid(row=notes_row + 1, column=0, columnspan=3,
                        sticky="ew", padx=5, pady=(0, 5))
        ttk.Label(meta_frame,
                  text="Start/end are recorded automatically. Other values are saved on exit; notes are always cleared for the next experiment.",
                  foreground="gray").grid(row=notes_row + 2, column=0, columnspan=3,
                                           sticky="w", padx=5, pady=(6, 0))

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(0, 10))
        self.run_button = ttk.Button(controls, text="Run experiment", command=self.run_experiment)
        self.run_button.pack(side="left")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(controls, textvariable=self.status).pack(side="left", padx=12)

        log_frame = ttk.LabelFrame(body, text="Live experiment output", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log = scrolledtext.ScrolledText(log_frame, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    def update_plot_controls(self):
        # main.py only generates plots with --plot, so live display requires saving.
        if self.plot_enabled.get():
            self.show_plots_checkbox.configure(state="normal")
        else:
            self.show_plots.set(False)
            self.show_plots_checkbox.configure(state="disabled")

    def poll_plots(self):
        """Display newly written images in separate Tk windows, never in the GUI."""
        try:
            directory = self.plot_directory
            if directory is not None and directory.is_dir():
                paths = sorted(
                    (p for p in directory.iterdir()
                     if p.is_file() and p.suffix.lower() in
                     (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")),
                    key=lambda p: (p.stat().st_mtime_ns, p.name),
                )
                for path in paths:
                    if path in self.plot_seen:
                        continue
                    try:
                        stat = path.stat()
                        signature = (stat.st_size, stat.st_mtime_ns)
                    except OSError:
                        continue
                    if self.plot_pending.get(path) != signature:
                        self.plot_pending[path] = signature
                        continue  # Wait for file to stop changing before opening.
                    if Image is None:
                        self.append_log("Plot display needs Pillow: uv add pillow\n")
                        self.plot_seen.add(path)
                        continue
                    try:
                        with Image.open(path) as source:
                            source.load()
                            picture = source.copy()
                        picture.thumbnail((1000, 750), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(picture)
                    except (OSError, ValueError):
                        continue  # Image may still be writing.
                    window = tk.Toplevel(self)
                    window.title(f"Experiment plot — {path.name}")
                    label = ttk.Label(window, image=photo)
                    label.image = photo
                    label.pack(fill="both", expand=True, padx=8, pady=8)
                    window.protocol("WM_DELETE_WINDOW", window.destroy)
                    self.plot_windows[path] = window
                    self.plot_seen.add(path)
                    self.append_log(f"Opened plot window: {path.name}\n")
        except OSError as exc:
            self.append_log(f"Plot monitoring error: {exc}\n")
        finally:
            self.after(700, self.poll_plots)

    def browse_script(self):
        filename = filedialog.askopenfilename(
            title="Select your experiment main.py", initialdir=str(HERE),
            filetypes=[("Python files", "*.py"), ("All files", "*")]
        )
        if filename:
            self.vars["script"].set(filename)

    def capture_notes(self):
        self.vars["Notes"].set(self.notes.get("1.0", "end-1c"))

    def build_command(self):
        script = Path(self.vars["script"].get().strip()).expanduser().resolve()
        if not script.is_file():
            raise ValueError(f"Main script not found: {script}")
        if script == Path(__file__).resolve():
            raise ValueError("Select the measurement main.py, not the GUI itself.")
        self.update_experiment_identity()
        name = self.vars["save"].get().strip()
        if not name or name in (".", "..") or Path(name).name != name:
            raise ValueError("Enter a simple experiment name (no folder separators).")
        port = self.vars["port"].get().strip()
        if not port:
            raise ValueError("Meter serial port is required.")
        baud = int(self.vars["baudrate"].get())
        avg = int(self.vars["average"].get())
        count = int(self.vars["count"].get())
        stage = int(self.vars["stage"].get())
        level = float(self.vars["level"].get())
        fmin = float(self.vars["freq_from"].get())
        fmax = float(self.vars["freq_to"].get())
        bias = numbers(self.vars["bias"].get(), "bias")
        positions = numbers(self.vars["positions"].get(), "positions")
        mode = self.vars["mode"].get()
        if baud <= 0 or avg <= 0 or count <= 0 or stage <= 0:
            raise ValueError("Baudrate, average, count and stage port must be positive.")
        if fmin <= 0 or fmax <= fmin:
            raise ValueError("Frequency limits must satisfy 0 < start < end.")
        if mode == "LTA" and len(bias) != 1:
            raise ValueError("LTA requires exactly one bias value.")
        cmd = [sys.executable, "-u", str(script), "--port", port,
               "--baudrate", str(baud), "--save", name,
               "--level", str(level), "--average", str(avg),
               "--from", str(fmin), "--to", str(fmax),
               "--count", str(count), "--mode", mode,
               "--stage", str(stage), "--bias", *bias,
               "--positions", *positions]
        cmd.append("--plot" if self.plot_enabled.get() else "--no-plot")
        return script, cmd

    def run_experiment(self):
        if self.running:
            return
        try:
            script, cmd = self.build_command()
            self.capture_notes()
            if not self.vars["Notes"].get().strip():
                self.notes.focus_set()
                raise ValueError("Notes are required. Enter notes describing this experiment before running.")
            self.save_settings()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Cannot start experiment", str(exc))
            return
        self.experiment_dir = None
        self.plot_directory = None
        self.plot_seen.clear()
        self.plot_pending.clear()
        self.display_plots_this_run = self.show_plots.get()
        self.start_time = timestamp()
        self.vars["Experiment Start"].set(self.start_time)
        self.vars["Experiment End"].set("")
        self.run_metadata = {field: self.vars[field].get() for field in METADATA_FIELDS}
        self.running = True
        self.run_button.configure(state="disabled")
        self.status.set("Running…")
        self.append_log("\n=== Starting experiment ===\n")
        self.append_log("Command: " + subprocess.list2cmdline(cmd) + "\n")
        # Reserve this experiment number before starting the worker.
        self.next_number += 1
        self.save_settings()
        threading.Thread(target=self.worker, args=(script, cmd), daemon=True).start()

    def worker(self, script, cmd):
        # main.py creates the folder under its current working directory.
        try:
            with subprocess.Popen(cmd, cwd=str(script.parent), stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace", bufsize=1) as proc:
                self.process = proc
                for line in proc.stdout:
                    self.events.put(("line", line, script.parent))
                return_code = proc.wait()
            self.events.put(("done", return_code))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def append_log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line)
        self.log.see("end")
        self.log.configure(state="disabled")

    def drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "line":
                    _, line, working_dir = event
                    self.append_log(line)
                    # main.py prints: Folder: /path/to/out/data/<experiment>
                    match = re.match(r"^Folder:\s*(.+?)\s*$", line)
                    if match and self.experiment_dir is None:
                        candidate = Path(match.group(1))
                        if not candidate.is_absolute():
                            candidate = working_dir / candidate
                        self.experiment_dir = candidate.resolve()
                        if self.display_plots_this_run:
                            self.plot_directory = self.experiment_dir
                elif event[0] == "done":
                    self.finish(event[1])
                elif event[0] == "error":
                    self.finish(None, event[1])
        except queue.Empty:
            pass
        self.after(100, self.drain_events)

    def finish(self, return_code, error=None):
        end_time = timestamp()
        self.vars["Experiment End"].set(end_time)
        self.run_metadata["Experiment End"] = end_time
        self.running = False
        self.process = None
        self.run_button.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.vars["Notes"].set("")
        self.update_experiment_identity()
        successful = return_code == 0
        self.status.set("Complete" if successful else "Failed / incomplete")
        self.append_log(f"\n=== Finished: {end_time}; exit code: {return_code} ===\n")
        if error:
            self.append_log(f"Error: {error}\n")
        if self.experiment_dir and self.experiment_dir.is_dir():
            try:
                import saver

                csv_files = [
                    p for p in self.experiment_dir.glob("*.csv")
                    if p.name != "metadata.csv"
                ]
                if len(csv_files) != 1:
                    raise ValueError(
                        "Expected exactly one measurement CSV, "
                        f"found {len(csv_files)}."
                    )

                measurement_csv = csv_files[0]
                saver.add_metadata_to_csv(
                    filepath=measurement_csv,
                    metadata=self.run_metadata,
                )
                self.append_log(f"Combined CSV saved: {measurement_csv}\n")
            except (OSError, ValueError) as exc:
                self.append_log(f"ERROR combining metadata: {exc}\n")
                messagebox.showerror("Metadata save failed", str(exc))
        else:
            self.append_log(
                "No experiment folder was reported; metadata could not be added.\n"
            )
        if not successful:
            messagebox.showwarning("Experiment incomplete", "Check the live output for errors. Any created experiment folder has been retained.")

    def on_close(self):
        if self.running:
            messagebox.showwarning("Experiment running", "Wait for the experiment to finish before closing this window.")
            return
        self.capture_notes()
        try:
            self.save_settings()
        except OSError as exc:
            messagebox.showerror("Settings error", f"Could not save entered values:\n{exc}")
            return
        self.plot_directory = None
        self.destroy()


if __name__ == "__main__":
    ExperimentGUI().mainloop()