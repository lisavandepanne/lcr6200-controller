"""Interactive comparison of GW Instek EIS experiment CSV files.

Run beside the project scripts with: uv run python visualizer.py
Requires matplotlib and numpy; Tkinter is included with most Python installs.
"""
from __future__ import annotations

import csv
from collections import defaultdict
import colorsys
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib import colormaps

HERE = Path(__file__).resolve().parent
ALIASES = {
    "frequency": ("Frequency (Hz)", "frequency_hz", "frequency", "freq"),
    "magnitude": ("Magnitude", "magnitude", "mag"),
    "phase": ("Phase (deg)", "phase_deg", "phase", "phase (degrees)"),
}


def find_column(fields, kind):
    normalized = {field.strip().casefold(): field for field in fields}
    return next((normalized[name.casefold()] for name in ALIASES[kind]
                 if name.casefold() in normalized), None)


@dataclass
class Experiment:
    path: Path
    rows: list[dict]
    fields: list[str]


def load_experiment(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = [kind for kind in ALIASES if not find_column(fields, kind)]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV has no measurement rows")
    return Experiment(path, rows, fields)


def group_curves(exp, label_col, color_col):
    """Group by chosen metadata AND measurement dimensions to avoid mixing sweeps."""
    freq_col = find_column(exp.fields, "frequency")
    mag_col = find_column(exp.fields, "magnitude")
    phase_col = find_column(exp.fields, "phase")
    # Bias and position distinguish physical sweeps even if neither is selected.
    dimension_cols = [c for c in ("Bias (V)", "Position (mm)") if c in exp.fields]
    group_cols = list(dict.fromkeys(c for c in (label_col, color_col, *dimension_cols)
                                    if c and c != "Experiment" and c in exp.fields))
    groups = defaultdict(lambda: defaultdict(lambda: [[], []]))
    for row in exp.rows:
        try:
            f, m, p = (float(row[col]) for col in (freq_col, mag_col, phase_col))
        except (TypeError, ValueError, KeyError):
            continue
        if not np.isfinite([f, m, p]).all() or f <= 0:
            continue
        key = tuple((col, row.get(col, "").strip()) for col in group_cols)
        groups[key][f][0].append(m)
        groups[key][f][1].append(p)
    result = []
    for key, frequencies in groups.items():
        if not frequencies:
            continue
        metadata = dict(key)
        fs = np.array(sorted(frequencies))
        mags = [np.asarray(frequencies[f][0], dtype=float) for f in fs]
        phases = [np.asarray(frequencies[f][1], dtype=float) for f in fs]
        result.append((metadata, fs,
                       np.array([x.mean() for x in mags]),
                       np.array([x.std() for x in mags]),
                       np.array([x.mean() for x in phases]),
                       np.array([x.std() for x in phases])))
    return result


class Visualizer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EIS Experiment Visualizer")
        self.geometry("1320x800")
        self.minsize(900, 550)
        self.experiments = {}
        self.selected = {}
        self.label_var = tk.StringVar(value="Experiment")
        self.color_var = tk.StringVar(value="Experiment")
        self.std_var = tk.BooleanVar(value=True)
        self.log_mag_var = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Open a folder or add CSV files to begin.")
        self._build()
        default = HERE / "out" / "data"
        if default.is_dir():
            self.add_paths(default.rglob("*.csv"))

    def _build(self):
        outer = ttk.PanedWindow(self, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        sidebar = ttk.Frame(outer, width=305)
        outer.add(sidebar, weight=0)
        chart_area = ttk.Frame(outer)
        outer.add(chart_area, weight=1)

        buttons = ttk.Frame(sidebar)
        buttons.pack(fill="x", pady=(0, 8))
        ttk.Button(buttons, text="Add CSVs", command=self.open_files).pack(side="left", padx=(0, 4))
        ttk.Button(buttons, text="Open folder", command=self.open_folder).pack(side="left")
        ttk.Button(sidebar, text="Reload CSV data", command=self.reload).pack(fill="x", pady=(0, 8))

        ttk.Label(sidebar, text="Experiments", font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
        actions = ttk.Frame(sidebar)
        actions.pack(fill="x", pady=4)
        ttk.Button(actions, text="Select all", command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(actions, text="Select none", command=lambda: self.set_all(False)).pack(side="left", padx=4)
        ttk.Button(actions, text="Remove unchecked", command=self.remove_unchecked).pack(side="left")
        list_container = ttk.Frame(sidebar)
        list_container.pack(fill="both", expand=True)
        self.list_canvas = tk.Canvas(list_container, width=270, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.list_canvas.yview)
        self.list_frame = ttk.Frame(self.list_canvas)
        self.list_frame.bind("<Configure>", lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all")))
        self.list_canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_canvas.configure(yscrollcommand=scrollbar.set)
        self.list_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        options = ttk.LabelFrame(sidebar, text="Plot settings", padding=8)
        options.pack(fill="x", pady=(10, 0))
        ttk.Label(options, text="Legend label by CSV column").pack(anchor="w")
        self.label_combo = ttk.Combobox(options, textvariable=self.label_var, state="readonly")
        self.label_combo.pack(fill="x", pady=(2, 8))
        ttk.Label(options, text="Colour code by CSV column").pack(anchor="w")
        self.color_combo = ttk.Combobox(options, textvariable=self.color_var, state="readonly")
        self.color_combo.pack(fill="x", pady=(2, 8))
        self.label_combo.bind("<<ComboboxSelected>>", lambda e: self.redraw())
        self.color_combo.bind("<<ComboboxSelected>>", lambda e: self.redraw())
        ttk.Checkbutton(options, text="Show ±1 standard deviation", variable=self.std_var,
                        command=self.redraw).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(options, text="Logarithmic magnitude axis", variable=self.log_mag_var,
                        command=self.redraw).pack(anchor="w")
        ttk.Button(options, text="Save figure…", command=self.save_figure).pack(fill="x", pady=(8, 0))

        self.figure = Figure(figsize=(11, 5.5), dpi=100, constrained_layout=True)
        self.ax_mag, self.ax_phase = self.figure.subplots(1, 2)
        self.canvas = FigureCanvasTkAgg(self.figure, master=chart_area)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, chart_area, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(fill="x")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=10, pady=(0, 5))
        self.update_columns()
        self.redraw()

    def open_files(self):
        paths = filedialog.askopenfilenames(title="Choose experiment CSV files", filetypes=[("CSV", "*.csv")])
        self.add_paths(map(Path, paths))

    def open_folder(self):
        folder = filedialog.askdirectory(title="Choose folder containing experiment CSVs")
        if folder:
            self.add_paths(Path(folder).rglob("*.csv"))

    def add_paths(self, paths):
        errors = []
        count = 0
        for path in sorted(set(Path(p).resolve() for p in paths)):
            if path in self.experiments:
                continue
            try:
                self.experiments[path] = load_experiment(path)
                self.selected[path] = tk.BooleanVar(value=True)
                count += 1
            except (OSError, ValueError, csv.Error) as exc:
                errors.append(f"{path.name}: {exc}")
        self.refresh_list()
        self.update_columns()
        self.redraw()
        self.status.set(f"Loaded {count} new CSV(s); {len(self.experiments)} total.")
        if errors:
            messagebox.showwarning("Some files were skipped", "\n".join(errors[:15]))

    def refresh_list(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        for path, exp in self.experiments.items():
            try:
                display = str(path.relative_to(HERE))
            except ValueError:
                display = path.name
            ttk.Checkbutton(self.list_frame, text=display, variable=self.selected[path],
                            command=self.redraw).pack(anchor="w", fill="x", pady=2)

    def update_columns(self):
        columns = sorted(set().union(*(set(exp.fields) for exp in self.experiments.values()))) if self.experiments else []
        choices = ["Experiment"] + columns
        for combo, var in ((self.label_combo, self.label_var), (self.color_combo, self.color_var)):
            combo.configure(values=choices)
            if var.get() not in choices:
                var.set("Experiment")

    def set_all(self, value):
        for var in self.selected.values():
            var.set(value)
        self.redraw()

    def remove_unchecked(self):
        for path in list(self.experiments):
            if not self.selected[path].get():
                del self.experiments[path]
                del self.selected[path]
        self.refresh_list()
        self.update_columns()
        self.redraw()

    def reload(self):
        errors = []
        for path in list(self.experiments):
            try:
                self.experiments[path] = load_experiment(path)
            except (OSError, ValueError, csv.Error) as exc:
                errors.append(f"{path.name}: {exc}")
        self.update_columns()
        self.redraw()
        if errors:
            messagebox.showwarning("Reload issues", "\n".join(errors[:15]))

    def redraw(self):
        self.ax_mag.clear()
        self.ax_phase.clear()
        label_col, color_col = self.label_var.get(), self.color_var.get()
        curves = []
        for path, exp in self.experiments.items():
            if not self.selected[path].get():
                continue
            for metadata, freq, mag, mag_std, phase, phase_std in group_curves(exp, label_col, color_col):
                # The legend and colour category contain ONLY their chosen CSV value.
                label = path.stem if label_col == "Experiment" else metadata.get(label_col, "(missing)")
                category = path.stem if color_col == "Experiment" else metadata.get(color_col, "(missing)")
                curves.append((str(category), str(label), freq, mag, mag_std, phase, phase_std))

        categories = sorted({curve[0] for curve in curves})
        # One distinct base hue per category. Repeated curves in a category get
        # lighter/darker shades of that same hue, without changing their labels.
        palette = colormaps["tab20"]
        base_colors = {
            category: palette((i % 10) * 2 / 20) if len(categories) <= 10
            else colormaps["hsv"](i / max(1, len(categories)))
            for i, category in enumerate(categories)
        }
        category_counts = defaultdict(int)
        for category, *_ in curves:
            category_counts[category] += 1
        category_seen = defaultdict(int)
        used_labels = set()
        for category, label, freq, mag, mag_std, phase, phase_std in curves:
            base = base_colors[category]
            index = category_seen[category]
            category_seen[category] += 1
            count = category_counts[category]
            if count == 1:
                color = base
            else:
                # Preserve hue; distribute shades across lightness and saturation.
                h, l, s = colorsys.rgb_to_hls(*base[:3])
                fraction = index / (count - 1)
                target_lightness = 0.28 + 0.48 * fraction
                color = colorsys.hls_to_rgb(h, target_lightness, max(0.45, s))

            # Duplicate legend labels appear once, exactly as written in the CSV.
            legend_label = label if label not in used_labels else "_nolegend_"
            used_labels.add(label)
            self.ax_mag.plot(freq, mag, color=color, lw=1.7, marker=".", ms=3, label=legend_label)
            self.ax_phase.plot(freq, phase, color=color, lw=1.7, marker=".", ms=3, label=legend_label)
            if self.std_var.get():
                self.ax_mag.fill_between(freq, mag - mag_std, mag + mag_std, color=color, alpha=0.13)
                self.ax_phase.fill_between(freq, phase - phase_std, phase + phase_std, color=color, alpha=0.13)
        for ax in (self.ax_mag, self.ax_phase):
            ax.set_xscale("log")
            ax.set_xlabel("Frequency (Hz)")
            ax.grid(True, which="both", ls="--", alpha=0.3)
        if self.log_mag_var.get() and all(np.all(curve[3] > 0) for curve in curves):
            self.ax_mag.set_yscale("log")
        self.ax_mag.set_title("Magnitude")
        self.ax_mag.set_ylabel("Magnitude")
        self.ax_phase.set_title("Phase")
        self.ax_phase.set_ylabel("Phase (degrees)")
        for legend in list(self.figure.legends):
            legend.remove()
        if curves:
            # One shared legend, leaving space beneath both panels.
            handles, labels = self.ax_mag.get_legend_handles_labels()
            self.figure.legend(handles, labels, loc="outside lower center", ncol=min(4, max(1, len(labels))), fontsize=8)
        # Clear old figure-level legends before adding the new one (handled below).
        self.canvas.draw_idle()
        self.status.set(f"Showing {len(curves)} curve(s) from {sum(v.get() for v in self.selected.values())} selected CSV(s).")

    def save_figure(self):
        target = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")])
        if target:
            try:
                self.figure.savefig(target, dpi=200)
                self.status.set(f"Saved {target}")
            except OSError as exc:
                messagebox.showerror("Save failed", str(exc))


if __name__ == "__main__":
    Visualizer().mainloop()
